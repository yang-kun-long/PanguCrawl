# app/services/planner.py
import json
import logging
import re
from typing import Dict, Any, List, AsyncGenerator
from app.services.llm import pangu_client
from app.utils import cluster_links

logger = logging.getLogger(__name__)


class CrawlPlanner:
    def __init__(self):
        self.plan_template = {
            "topic": "通用爬取任务",
            "seed_urls": [],
            "max_depth": 2,
            "max_pages": 10
        }
        self.model_explorer = "Qwen/Qwen2.5-72B-Instruct"
        self.model_critic = "deepseek-ai/DeepSeek-V3"
        self.model_moderator = "ascend-tribe/pangu-pro-moe"

    def _clean_json_string(self, json_str: str) -> str:
        """
        超级鲁棒的 JSON 清洗：
        1. 去除 Markdown
        2. 强制截取第一个 { 到 最后一个 }，丢弃所有首尾噪音
        """
        if not json_str:
            return ""

        # 1. 移除 Markdown 标记
        cleaned = re.sub(r"^```json\s*", "", json_str, flags=re.MULTILINE)
        cleaned = re.sub(r"^```\s*", "", cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r"```$", "", cleaned, flags=re.MULTILINE)
        cleaned = cleaned.strip()

        # 2. 强制截取 JSON 核心区 (解决 Extra data 问题)
        try:
            start = cleaned.find('{')
            end = cleaned.rfind('}')
            if start != -1 and end != -1:
                return cleaned[start: end + 1]
        except Exception:
            pass

        return cleaned

    async def generate_plan(self, user_request: str) -> Dict[str, Any]:
        """生成初始计划，增加正则兜底"""
        logger.info(f"🧠 Planner is thinking about: {user_request}")

        system_prompt = f"""
你是一个爬虫规划师。请提取用户指令中的 URL 和目标。
输出 JSON:
{json.dumps(self.plan_template, ensure_ascii=False, indent=2)}
"""
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_request}]

        plan = self.plan_template.copy()

        try:
            raw = await pangu_client.chat_completion(messages, temperature=0.01)
            # 记录原始返回以便调试
            # logger.info(f"LLM Raw Plan: {raw}")

            clean_json = self._clean_json_string(raw)
            plan = json.loads(clean_json)

            logger.info(f"✅ Planner JSON Parsed Success. Seeds: {plan.get('seed_urls')}")

        except Exception as e:
            logger.error(f"PLANNER JSON ERROR: {e}. Falling back to Regex.")
            # JSON 解析失败，plan 保持为 template，但在下面会尝试补救

        # --- 🛡️ 正则救援行动 (Regex Rescue) ---
        # 无论 JSON 是否成功，如果 seed_urls 是空的，我们都尝试从用户输入里硬抓 URL
        if not plan.get("seed_urls"):
            logger.info("🔍 No seeds in JSON, attempting Regex extraction from user input...")
            # 匹配 http/https 链接
            urls = re.findall(r'https?://[^\s,;"\'\]\)]+', user_request)
            if urls:
                plan["seed_urls"] = urls
                logger.info(f"🚑 Regex rescued {len(urls)} URLs: {urls}")
            else:
                logger.warning("⚠️ No URLs found in JSON or via Regex!")

        return plan

    async def run_debate_stream(self, user_request: str, current_layer_id: str, candidates: List[Dict[str, str]]) -> \
    AsyncGenerator[Dict[str, Any], None]:
        # ... (保持原有的辩论逻辑不变) ...
        if not candidates:
            yield {"role": "系统", "content": "本层无新链接，跳过会议。", "final_result": []}
            return

        clusters = cluster_links(candidates)

        # 限制 clusters 数量，防止 Token 爆炸
        if len(clusters) > 15:
            clusters = clusters[:15]

        cluster_info = {}
        links_preview = ""
        for i, cluster in enumerate(clusters):
            cluster_id = f"C_{i + 1}"  # 缩短 ID 节省 Token
            cluster_info[cluster_id] = cluster
            links_preview += f"\n- {cluster_id} (x{cluster['count']}): {cluster['representative_text']} [路径: {cluster['cluster_id']}]"

        yield {"role": "系统", "content": f"发现 {len(candidates)} 个链接，聚类为 {len(clusters)} 组。"}

        # --- Round 1: Explorer ---
        prompt_explorer = f"目标：{user_request}\n待选：\n{links_preview}\n请选出所有【可能相关】的组号(C_x)。"
        res_explorer = await pangu_client.chat_completion(
            [{"role": "user", "content": prompt_explorer}], model=self.model_explorer, temperature=0.7
        )
        yield {"role": "激进派", "content": res_explorer}

        # --- Round 2: Critic ---
        prompt_critic = f"目标：{user_request}\n激进派建议：{res_explorer}\n清单：\n{links_preview}\n请剔除广告、无关、登录页。指出需要保留的组号。"
        res_critic = await pangu_client.chat_completion(
            [{"role": "user", "content": prompt_critic}], model=self.model_critic, temperature=0.3
        )
        yield {"role": "保守派", "content": res_critic}

        # --- Round 3: Moderator ---
        prompt_moderator = f"""
综合意见：
激进: {res_explorer}
保守: {res_critic}

请输出最终决定的组号列表 JSON，如 ["C_1", "C_3"]。只输出 JSON。
"""
        res_moderator = await pangu_client.chat_completion(
            [{"role": "system", "content": "JSON array only"}, {"role": "user", "content": prompt_moderator}],
            model=self.model_moderator, temperature=0.1
        )

        selected_urls = []
        try:
            cleaned = self._clean_json_string(res_moderator)
            selected_ids = json.loads(cleaned)
            if isinstance(selected_ids, list):
                for cid in selected_ids:
                    if cid in cluster_info:
                        selected_urls.extend([l['url'] for l in cluster_info[cid]['links']])
        except:
            logger.error("Debate JSON failed")

        final_msg = f"裁决：选中 {len(selected_urls)} 个链接进入下一层。"
        yield {"role": "主持人", "content": final_msg, "final_result": selected_urls}


crawl_planner = CrawlPlanner()