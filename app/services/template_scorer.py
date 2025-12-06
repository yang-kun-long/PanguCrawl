# app/services/template_scorer.py

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
    把 URL 归一成“模板形式”，比如：
    /teacher/123.html, /teacher/456.html -> /teacher/{id}.html
    /teacher?id=123 -> /teacher?id={id}
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return "unknown"

    path_parts = [p for p in parsed.path.split("/") if p]

    norm_parts = []
    for part in path_parts:
        # 全数字 / 明显是 id 的部分，统一成 {id}
        if re.fullmatch(r"\d+", part):
            norm_parts.append("{id}")
        elif re.fullmatch(r"[0-9a-fA-F\-]{6,}", part):
            norm_parts.append("{id}")
        else:
            norm_parts.append(part.lower())

    norm_path = "/" + "/".join(norm_parts) if norm_parts else "/"

    # query 里简单把 =数字 归一成 ={id}
    norm_query = parsed.query
    if norm_query:
        norm_query = re.sub(r"=\d+", "={id}", norm_query)

    if norm_query:
        return norm_path + "?" + norm_query
    return norm_path


def _extract_field_names(markdown: str) -> List[str]:
    """
    从文本里粗略抓“字段名”，例如：
    姓名：张三
    职称: 副教授
    Email：xxx@xx
    这里只有“冒号前”的部分。
    """
    if not markdown:
        return []

    field_names = set()
    snippet = markdown[:4000]  # 不看太长

    # 中英字段名 + 冒号/：
    pattern = re.compile(r"([\u4e00-\u9fa5A-Za-z0-9_]{2,20})\s*[：:]\s")

    for match in pattern.finditer(snippet):
        name = match.group(1).strip()
        if len(name) < 2:
            continue
        if name in {"http", "https"}:
            continue
        field_names.add(name)

    return list(field_names)


def _extract_field_values(markdown: str, field_names: List[str]) -> Dict[str, str]:
    """
    按 “字段名：值” 抓一下值（只取第一次），
    只是用来判断“不同页面上值是不是不一样”，不是最终抽取用。
    """
    values: Dict[str, str] = {}
    if not markdown or not field_names:
        return values

    lines = markdown.splitlines()
    for line in lines:
        line_stripped = line.strip()
        for name in field_names:
            if not line_stripped.startswith(name):
                continue
            m = re.match(rf"{re.escape(name)}\s*[：:]\s*(.+)", line_stripped)
            if m and name not in values:
                val = m.group(1).strip()
                if val:
                    values[name] = val
        if len(values) == len(field_names):
            break

    return values


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _compute_local_structure_score(markdown: str) -> float:
    """
    单页粗略结构分：
    - 文本长度
    - 冒号行数量（像“字段：值”的行）
    - markdown 表格符号 |
    """
    if not markdown:
        return 0.0

    text = markdown[:6000]
    length = len(text)

    # 基础分：长度
    if length < 200:
        base = 0.2
    elif length < 800:
        base = 0.5
    elif length < 2000:
        base = 0.7
    else:
        base = 0.85

    # 像“姓名：张三”这种行
    lines = text.splitlines()
    colon_lines = sum(1 for ln in lines if "：" in ln or ":" in ln)
    if colon_lines >= 3:
        base += 0.1
    elif colon_lines >= 1:
        base += 0.05

    # markdown 表格行
    table_lines = sum(1 for ln in lines if "|" in ln and "---" in ln)
    if table_lines >= 1:
        base += 0.1

    return float(max(0.0, min(1.0, base)))


def score_page_results_for_task(task: CrawlTask, db: Session, min_pages_per_template: int = 3) -> None:
    """
    对一个任务下所有 PageResult 做“模板结构打分”，并写回 PageResult.media_info["meta"]。

    - 先按 URL 模板归类（老师详情页会被聚到一类）
    - 在每个模板簇上统计字段名 / 字段值分布 -> template_score
    - 和单页 local_structure_score 合并成最终 structure_score
    """
    pages: List[PageResult] = [
        r for r in task.results
        if r.status_code == 200 and (r.markdown_content or "")
    ]

    if not pages:
        logger.info(f"[template_scorer] task {task.id}: no valid pages to score.")
        return

    # 先给每页算一个本地结构分
    for page in pages:
        media = page.media_info or {}
        meta = dict(media.get("meta") or {})
        md = page.markdown_content or ""
        local_score = _compute_local_structure_score(md)
        meta["local_structure_score"] = float(f"{local_score:.3f}")
        media["meta"] = meta
        page.media_info = media
        flag_modified(page, "media_info")

    # 1. 按 URL 模板分组
    pattern_map: Dict[str, List[PageResult]] = {}
    for page in pages:
        pattern = _normalize_url_pattern(page.url or "")
        pattern_map.setdefault(pattern, []).append(page)

    logger.info(f"[template_scorer] task {task.id}: grouped into {len(pattern_map)} url patterns")

    # 2. 对每个模板簇算 template_score 并回填
    for pattern, group in pattern_map.items():
        if len(group) < min_pages_per_template:
            continue  # 页面太少，不当模板簇处理

        page_count = len(group)

        field_name_counter: Dict[str, int] = {}
        field_values_per_field: Dict[str, set] = {}

        for page in group:
            md = page.markdown_content or ""
            names = _extract_field_names(md)
            values = _extract_field_values(md, names)

            for n in names:
                field_name_counter[n] = field_name_counter.get(n, 0) + 1
            for n, v in values.items():
                field_values_per_field.setdefault(n, set()).add(v)

        if not field_name_counter:
            continue

        # 出现频率 >= 60% 的字段名，视为“稳定字段名”
        stable_fields = [
            name for name, cnt in field_name_counter.items()
            if cnt / page_count >= 0.6
        ]
        total_fields = max(len(field_name_counter), 1)
        stability_score = len(stable_fields) / total_fields  # 0~1

        # 字段值多样性：同一个字段在不同页面值越不一样越好
        diversity_scores: List[float] = []
        for name in stable_fields:
            vals = field_values_per_field.get(name, set())
            if not vals:
                continue
            diversity_scores.append(_sigmoid(len(vals) - 1.0))  # 1 个值 ~0.5，多了接近 1

        diversity_score = sum(diversity_scores) / len(diversity_scores) if diversity_scores else 0.0

        # 模板簇大小权重：页面越多越信
        size_score = _sigmoid((page_count - min_pages_per_template) / 3.0)

        template_score = (
            0.5 * stability_score +
            0.3 * diversity_score +
            0.2 * size_score
        )
        template_score = float(max(0.0, min(1.0, template_score)))

        logger.info(
            f"[template_scorer] task={task.id} pattern={pattern} "
            f"pages={page_count} stable_fields={len(stable_fields)} "
            f"template_score={template_score:.3f}"
        )

        # 回填到每个页面
        for page in group:
            media = page.media_info or {}
            meta = dict(media.get("meta") or {})

            local_score = float(meta.get("local_structure_score", 0.0))
            final_score = 0.4 * local_score + 0.6 * template_score

            meta["template_pattern"] = pattern
            meta["page_count_in_template"] = page_count
            meta["stable_field_count"] = len(stable_fields)
            meta["template_score"] = float(f"{template_score:.3f}")
            meta["structure_score"] = float(f"{final_score:.3f}")

            media["meta"] = meta
            page.media_info = media
            flag_modified(page, "media_info")

    db.commit()
