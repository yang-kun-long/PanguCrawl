import json
import logging
import re
from collections import Counter
from typing import Any, Dict, List

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models import CrawlTask, CrawlPlan, PageResult
from app.services.llm import pangu_client
from app.services.structure_scorer import _normalize_url_pattern

logger = logging.getLogger(__name__)


def _clean_json_string(s: str) -> str:
    if not s: return ""
    txt = s.strip()
    txt = re.sub(r"^```json\s*", "", txt, flags=re.MULTILINE)
    txt = re.sub(r"^```\s*", "", txt, flags=re.MULTILINE)
    txt = re.sub(r"```$", "", txt, flags=re.MULTILINE)
    try:
        matches = re.search(r"(\{.*\})", txt, re.DOTALL)
        if matches:
            return matches.group(1)
    except:
        pass
    return txt


class SchemaDiscoveryService:

    # 🟢 [通用算法] 统计学去噪
    # 不依赖任何 Prompt，纯靠数学规律发现“导航栏”并切除
    def _statistical_denoise(self, group: List[PageResult]) -> List[str]:
        """
        输入一组页面，返回一组去噪后的纯净文本样本。
        原理：计算每一行文本在组内的出现频率 (Document Frequency)。
        如果某行出现在 > 60% 的页面中，视为模板噪音，直接物理删除。
        """
        if not group:
            return []

        # 1. 采样：如果组很大，只取前 20 个做统计基数
        calc_subset = group[:20]

        # 2. 统计行频
        line_counter = Counter()
        for p in calc_subset:
            content = p.markdown_content or ""
            # 只统计有一定长度的行，避免误删短词
            lines = set([l.strip() for l in content.split('\n') if len(l.strip()) > 5])
            for line in lines:
                line_counter[line] += 1

        # 3. 定义噪音阈值 (60%)
        # 任何导航栏、Footer、版权声明，在同组页面里的出现率通常是 100%
        threshold = max(2, len(calc_subset) * 0.6)
        noise_set = {line for line, count in line_counter.items() if count >= threshold}

        logger.info(f"🧹 [Schema Discovery] Identified {len(noise_set)} common template lines to remove.")

        # 4. 生成干净的样本
        # 选取内容最丰富的 2 个页面作为 Schema 分析的样本
        samples = sorted(group, key=lambda x: len(x.markdown_content or ""), reverse=True)[:2]
        clean_samples_text = []

        for p in samples:
            original_lines = (p.markdown_content or "").split('\n')
            # 🔪 物理切割噪音
            clean_lines = [l for l in original_lines if l.strip() not in noise_set]
            clean_text = "\n".join(clean_lines)
            clean_samples_text.append(clean_text)

        return clean_samples_text

    async def discover_for_task(self, task_id: str, db: Session) -> List[Dict[str, Any]]:
        task = db.query(CrawlTask).filter(CrawlTask.id == task_id).first()
        if not task or not task.results:
            return []

        # 1. 聚类
        pattern_map = {}
        for p in task.results:
            if p.status_code != 200 or not p.markdown_content: continue
            pattern = _normalize_url_pattern(p.url or "")
            pattern_map.setdefault(pattern, []).append(p)

        logger.info(f"[schema_discovery] task {task_id}: {len(pattern_map)} patterns")
        schemas = []

        # 2. 分析样本
        for pattern, group in pattern_map.items():
            if len(group) < 2: continue

            # 🟢 使用统计学去噪后的样本
            # AI 此时看到的已经是没有导航栏的“干货”了
            clean_samples = self._statistical_denoise(group)

            sample_prompt_text = ""
            for i, text in enumerate(clean_samples):
                # 截取前 5000 字，去噪后这通常包含了整个正文
                sample_prompt_text += f"\n=== SAMPLE {i + 1} ===\n{text[:5000]}\n"

            # 🟢 通用 Prompt：不再包含 specific 的业务规则
            # 因为数据已经干净了，我们只需要告诉 AI "基于用户需求提取结构" 即可
            system_prompt = f"""
你是通用网页结构分析师。
你的任务是：基于【用户需求】，从【网页正文样本】中定义数据 Schema。

【用户需求】："{task.user_request}"

【规则】：
1. 样本已经过预处理，去除了大部分网站通用导航。
2. 请专注于剩下的内容，寻找与用户需求匹配的实体（Entity）。
3. 如果正文包含相关数据，请定义字段（如 name, title, content 等）；字段名请使用 snake_case 英文。
4. 如果正文看起来与需求无关（例如只是无意义的链接列表），返回 {{"fields": []}}。

【输出格式】：
只返回 JSON 对象，不要Markdown。
"""
            user_prompt = f"网页正文样本:\n{sample_prompt_text}\n\n请生成 Schema JSON:"

            try:
                # 使用 DeepSeek-V3 这种强推理模型
                raw = await pangu_client.chat_completion(
                    [{"role": "system", "content": system_prompt},
                     {"role": "user", "content": user_prompt}],
                    temperature=0.1,
                    model="deepseek-ai/DeepSeek-V3"
                )

                schema = json.loads(_clean_json_string(raw))
                fields = schema.get("fields", [])

                if not fields:
                    logger.info(f"🚫 Pattern {pattern} ignored (No relevant data found in cleaned text)")
                    continue

                # 简单校验：字段名全是 generic 的（如 link1, link2）通常是分析失败
                field_names = {f.get('name', '').lower() for f in fields}
                if len(field_names) > 0:
                    schema["template_pattern"] = pattern
                    schemas.append(schema)
                    logger.info(f"✅ Schema found for {pattern}: {list(field_names)}")

            except Exception as e:
                logger.warning(f"Schema Gen Error for {pattern}: {e}")

        # 保存
        if task.plan:
            data = task.plan.plan_data or {}
            data["schemas"] = schemas
            task.plan.plan_data = data
            flag_modified(task.plan, "plan_data")
            db.commit()

        return schemas


schema_discovery = SchemaDiscoveryService()