import logging
import json
import asyncio
import itertools
import random
import re
from collections import Counter
from typing import Any, Dict, List

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.config import API_KEY_POOL
from app.models import CrawlTask, PageResult
from app.services.llm import pangu_client

logger = logging.getLogger(__name__)

_key_cycle = itertools.cycle(API_KEY_POOL) if API_KEY_POOL else None


def _get_next_api_key():
    if _key_cycle:
        return next(_key_cycle)
    return None


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


class StructuredExtractor:

    def _compute_and_remove_noise(self, pages: List[PageResult]) -> Dict[str, str]:
        """
        计算并移除噪音。
        [修改]: 降低阈值，且无论是否去噪，都确保填充 cleaned_markdown 字段。
        """
        if not pages:
            return {}

        cleaned_map = {}
        total_pages = len(pages)

        # 1. 如果样本太少(<2)，无法统计共性，直接使用原始内容
        if total_pages < 2:
            for p in pages:
                content = p.markdown_content or ""
                cleaned_map[p.url] = content
                # 存入DB以便前端显示
                media = dict(p.media_info or {})
                media['cleaned_markdown'] = content
                p.media_info = media
                flag_modified(p, "media_info")
            return cleaned_map

        # 2. 统计文档频率
        line_counter = Counter()
        page_lines_map = {}

        for p in pages:
            content = p.markdown_content or ""
            # 只统计有意义的行
            lines = set([l.strip() for l in content.split('\n') if len(l.strip()) > 4])
            page_lines_map[p.url] = content.split('\n')
            for line in lines:
                line_counter[line] += 1

        # 3. 动态阈值：只要在 60% 的页面里出现，就视为噪音（导航栏通常是 100% 出现）
        threshold = max(2, int(total_pages * 0.6))
        noise_set = {line for line, count in line_counter.items() if count >= threshold}

        logger.info(f"🧹 [Denoise] Found {len(noise_set)} noise lines (Threshold: {threshold}/{total_pages})")

        # 4. 清洗并保存
        for p in pages:
            original_lines = page_lines_map[p.url]
            # 过滤噪音
            clean_lines = [line for line in original_lines if line.strip() not in noise_set]
            cleaned_text = "\n".join(clean_lines)
            cleaned_map[p.url] = cleaned_text

            # 保存到 JSONB
            media = dict(p.media_info or {})
            media['cleaned_markdown'] = cleaned_text
            p.media_info = media
            flag_modified(p, "media_info")

        return cleaned_map

    async def extract_single_page(self, page: PageResult, cleaned_content: str, schema: Dict[str, Any],
                                  user_request: str) -> Dict[str, Any] | None:
        if not cleaned_content or len(cleaned_content) < 10:
            return None

        # 🟢 [关键修改] Prompt 微调：不仅忽略噪音，还要具备“沙里淘金”的能力
        system_prompt = f"""
你是一个专业的数据提取助手。
【任务】：根据用户需求 "{user_request}"，从网页文本中提取结构化数据。
【Schema】：{json.dumps(schema['fields'], ensure_ascii=False)}

【处理策略】：
1. **沙里淘金**：网页可能依然残留大量无关链接或导航。请跳过它们，**寻找夹杂在其中的具体实体信息**（如正文中的人名、简介、参数）。
2. **拒绝误判**：不要因为开头是链接列表就直接放弃。请往后读，直到确认真的没有有效信息。
3. **严格格式**：只输出 JSON。如果确认页面无有效数据，返回 {{}}。
"""
        # 截断：为了防止 token 超限，截取前 6000 字符 (通常去噪后这已经包含整个页面了)
        user_prompt = f"去噪后的网页内容:\n{cleaned_content[:6000]}\n\nJSON:"

        MODEL_CHAIN = [
            "deepseek-ai/DeepSeek-V3",
            "Qwen/Qwen2.5-7B-Instruct"
        ]

        max_retries = 3

        for attempt in range(max_retries):
            current_key = _get_next_api_key()
            current_model = MODEL_CHAIN[attempt % len(MODEL_CHAIN)]

            try:
                resp = await pangu_client.chat_completion(
                    [{"role": "system", "content": system_prompt},
                     {"role": "user", "content": user_prompt}],
                    temperature=0.1,  # 降低温度，更严谨
                    model=current_model,
                    api_key=current_key
                )

                clean_json = _clean_json_string(resp)
                if not clean_json: continue

                data = json.loads(clean_json)

                if not data: return None
                if isinstance(data, dict) and all(not v for v in data.values()): return None

                data["source_url"] = page.url
                data["title"] = page.title
                return data

            except Exception as e:
                if attempt < max_retries - 1:
                    wait_time = 1 + random.uniform(0, 1)
                    await asyncio.sleep(wait_time)
                else:
                    return None

    async def extract_for_task_async(
            self,
            task_id: str,
            db: Session,
            schemas: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        task = db.query(CrawlTask).filter(CrawlTask.id == task_id).first()
        if not task or not task.results or not schemas:
            return {"task_id": task_id, "templates": []}

        # 智能选择 Schema
        target_schema = schemas[0]
        # 优先选字段丰富的 Schema，通常导航页 Schema 字段很少
        best_field_count = 0
        for s in schemas:
            field_count = len(s.get('fields', []))
            # 排除明显是导航的
            etype = s.get('entity_type', '').lower()
            if 'nav' not in etype and field_count > best_field_count:
                target_schema = s
                best_field_count = field_count

        valid_pages = [p for p in task.results if p.status_code == 200]

        # 1. 先去噪，并回写 DB
        logger.info("🧹 Computing template noise and cleaning pages...")
        cleaned_content_map = self._compute_and_remove_noise(valid_pages)
        db.commit()  # 提交 cleaned_markdown 到数据库

        pool_size = len(API_KEY_POOL) if API_KEY_POOL else 1
        CONCURRENCY = min(pool_size * 5, 50)

        logger.info(f"🚀 Starting Extraction ({len(valid_pages)} pages) | Concurrency: {CONCURRENCY}")

        semaphore = asyncio.Semaphore(CONCURRENCY)
        completed_count = 0

        async def worker(p):
            nonlocal completed_count
            async with semaphore:
                clean_text = cleaned_content_map.get(p.url, "")
                res = await self.extract_single_page(p, clean_text, target_schema, task.user_request)

                completed_count += 1
                if completed_count % 10 == 0 or completed_count == len(valid_pages):
                    logger.info(
                        f"⏳ Progress: {completed_count}/{len(valid_pages)} ({(completed_count / len(valid_pages)) * 100:.1f}%)")
                return res

        tasks = [worker(p) for p in valid_pages]
        results = await asyncio.gather(*tasks)

        valid_results = [r for r in results if r is not None]
        logger.info(f"✅ Extraction Done. {len(valid_results)} valid records.")

        return {
            "task_id": task_id,
            "templates": [{
                "template_pattern": "universal_ai",
                "entity_type": target_schema.get("entity_type", "extracted_data"),
                "record_count": len(valid_results),
                "records": [{"fields": r} for r in valid_results]
            }]
        }


structured_extractor = StructuredExtractor()