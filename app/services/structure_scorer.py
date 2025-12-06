import logging
import math
import re
from typing import Dict, List
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from urllib.parse import urlparse
from app.models import CrawlTask, PageResult

logger = logging.getLogger(__name__)


def _normalize_url_pattern(url: str) -> str:
    """
    把 URL 归一成模板形式，方便发现“同一类页面”
    [Upgrade]: 增强了对混合型 ID (如 njjkylnznyjzx2) 的识别能力，
    使其能像 Planner 那样成功聚类。
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return "unknown"

    path_parts = [p for p in parsed.path.split("/") if p]

    norm_parts: List[str] = []
    for part in path_parts:
        # 1. 纯数字 -> {id}
        if re.fullmatch(r"\d+", part):
            norm_parts.append("{id}")
        # 2. 标准 Hex 哈希 -> {id}
        elif re.fullmatch(r"[0-9a-fA-F\-]{6,}", part):
            norm_parts.append("{id}")
        # 3. [关键修复] 字母数字混合且长度 > 3 (针对 njjkylnznyjzx2 这类 ID)
        elif re.search(r"\d", part) and re.search(r"[a-zA-Z]", part) and len(part) > 3:
            norm_parts.append("{id}")
        # 4. [关键修复] 纯长字母乱码 (长度 > 12)，通常也是 slug 或 hash
        elif len(part) > 12 and re.fullmatch(r"[a-zA-Z]+", part):
            norm_parts.append("{id}")
        # 5. [兜底] 如果包含 index.htm/html，通常保留 index，去掉后缀
        elif part.lower() in ['index.htm', 'index.html', 'default.aspx']:
            norm_parts.append('index')
        else:
            norm_parts.append(part.lower())

    norm_path = "/" + "/".join(norm_parts) if norm_parts else "/"

    # query 参数也做模糊化
    norm_query = parsed.query
    if norm_query:
        # 把所有 =后面的数字或长字符串都变成 {id}
        norm_query = re.sub(r"=[\w\-]{5,}", "={id}", norm_query)
        norm_query = re.sub(r"=\d+", "={id}", norm_query)
        return norm_path + "?" + norm_query

    return norm_path


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _compute_local_structure_score(text: str) -> float:
    """单页结构粗打分：长度 + 冒号行 + 表格痕迹"""
    if not text:
        return 0.0

    t = text[:8000]
    length = len(t)

    # 长度
    if length < 200:
        base = 0.2
    elif length < 800:
        base = 0.5
    elif length < 2000:
        base = 0.7
    else:
        base = 0.85

    lines = t.splitlines()

    # 像“字段：值”的行
    colon_lines = sum(1 for ln in lines if ("：" in ln or ":" in ln) and len(ln.strip()) > 4)
    if colon_lines >= 5:
        base += 0.15
    elif colon_lines >= 2:
        base += 0.08
    elif colon_lines >= 1:
        base += 0.03

    # markdown 表格简单痕迹
    table_header_lines = sum(1 for ln in lines if "|" in ln and "---" in ln)
    if table_header_lines >= 1:
        base += 0.1

    return float(max(0.0, min(1.0, base)))


def _extract_field_names(text: str) -> List[str]:
    """从文本里粗抓字段名（X：Y 里的 X）"""
    if not text:
        return []

    snippet = text[:4000]
    # 稍微放宽一点字段提取正则
    pattern = re.compile(r"([\u4e00-\u9fa5A-Za-z0-9_]{2,20})\s*[：:]\s")
    names = set()

    for m in pattern.finditer(snippet):
        name = m.group(1).strip()
        # 排除常见误判
        if len(name) < 2 or name.lower() in {"http", "https", "tel", "email"}:
            continue
        names.add(name)

    return list(names)


def score_task_structure(task_id: str, db: Session) -> None:
    """
    对 task 的 PageResult 打分并计算 Template Score
    """
    task: CrawlTask | None = db.query(CrawlTask).filter(CrawlTask.id == task_id).first()
    if not task:
        logger.warning(f"[structure_scorer] task {task_id} not found")
        return

    pages: List[PageResult] = [
        r for r in task.results
        if r.status_code == 200 and (r.markdown_content or "")
    ]
    if not pages:
        logger.info(f"[structure_scorer] task {task_id}: no valid pages")
        return

    # 1. 单页结构分
    for p in pages:
        txt = p.markdown_content or ""
        local = _compute_local_structure_score(txt)
        media = p.media_info or {}
        structure = dict(media.get("structure") or {})
        structure["local_structure_score"] = float(f"{local:.3f}")
        media["structure"] = structure
        p.media_info = media
        flag_modified(p, "media_info")

    # 2. 按 URL 模板分组 (使用升级后的 normalize 逻辑)
    pattern_map: Dict[str, List[PageResult]] = {}
    for p in pages:
        pattern = _normalize_url_pattern(p.url or "")
        pattern_map.setdefault(pattern, []).append(p)

    # 打印日志以便调试聚类效果
    logger.info(f"[structure_scorer] task {task_id}: {len(pages)} pages -> {len(pattern_map)} patterns")
    for pat, grp in list(pattern_map.items())[:5]:
        logger.info(f"   Pattern: {pat} (Count: {len(grp)})")

    # 3. 计算 template_score
    for pattern, group in pattern_map.items():
        # 这里阈值可以稍微放低一点点，防止刚好只有 2 个样本的情况
        if len(group) < 2:
            continue

        page_count = len(group)
        field_name_counter: Dict[str, int] = {}

        for p in group:
            names = _extract_field_names(p.markdown_content or "")
            for n in names:
                field_name_counter[n] = field_name_counter.get(n, 0) + 1

        if not field_name_counter:
            continue

        stable_fields = [
            name for name, cnt in field_name_counter.items()
            if cnt / page_count >= 0.6
        ]
        total_fields = max(len(field_name_counter), 1)
        stability_score = len(stable_fields) / total_fields
        size_score = _sigmoid((page_count - 3) / 3.0)

        template_score = float(
            max(0.0, min(1.0, 0.7 * stability_score + 0.3 * size_score))
        )

        for p in group:
            media = p.media_info or {}
            structure = dict(media.get("structure") or {})
            local = float(structure.get("local_structure_score", 0.0))
            final = 0.4 * local + 0.6 * template_score

            structure["template_pattern"] = pattern
            structure["page_count_in_pattern"] = page_count
            structure["stable_field_count"] = len(stable_fields)
            structure["template_score"] = float(f"{template_score:.3f}")
            structure["structure_score"] = float(f"{final:.3f}")

            media["structure"] = structure
            p.media_info = media
            flag_modified(p, "media_info")

    db.commit()
    logger.info(f"[structure_scorer] task {task_id}: structure score updated")