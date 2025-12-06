# app/services/analyzer.py
import logging
from sqlalchemy.orm import Session
from app.models import CrawlTask
from app.services.llm import pangu_client

logger = logging.getLogger(__name__)


class ResultAnalyzer:
    async def analyze_task(self, task_id: str, db: Session) -> str:
        logger.info(f"🧠 Analyzing task {task_id} (Structure-Aware Mode)...")

        task = db.query(CrawlTask).filter(CrawlTask.id == task_id).first()
        if not task or not task.results:
            return ""

        # 1. 选页面：优先按照 structure_score 排序
        pages = [r for r in task.results if r.status_code == 200 and (r.markdown_content or "")]
        if not pages:
            return "未抓取到任何有效网页内容。"

        def get_structure_score(r):
            try:
                media = r.media_info or {}
                s = media.get("structure") or {}
                return float(s.get("structure_score", 0.0))
            except Exception:
                return 0.0

        # 按结构分从高到低排序，取前 10 个
        pages_sorted = sorted(pages, key=get_structure_score, reverse=True)
        useful_results = pages_sorted[:10]

        # 2. 拼接上下文：每个页面取“头 + 尾”，避免只看到导航
        context_text = ""
        for i, res in enumerate(useful_results):
            content = res.markdown_content or ""
            length = len(content)
            head = content[:2000]
            tail = content[-3000:] if length > 5000 else ""
            preview = head + ("\n...\n" if tail else "") + tail

            context_text += (
                f"\n=== 来源页面 {i + 1}: {res.title} ({res.url}) ===\n"
                f"{preview}\n"
            )

        # 3. Prompt：弱化“导航偏见”，只要是规律列表，就当数据
        prompt = f"""
你是一个高级信息提取模型，现在要根据【用户需求】从【网页内容】中提取结构化结果或给出总结。

【用户需求】：
"{task.user_request}"

【网页内容片段】（可能包含导航、菜单、正文和表格等混合内容）：
{context_text}

【非常重要的规则】：
1. 不要因为内容看起来像“导航栏”或“菜单”就直接放弃。
   - 只要出现大量人物 / 课程 / 条目等的**规律性列表**（例如一串姓名 + 职称 + 单位），即使它出现在侧边栏，也应视为可用数据并尝试提取。
2. 如果能找到满足用户需求的内容（例如包含姓名、职称、研究方向等字段的重复结构），请优先从这些内容中提取。
3. 只有在**确认整个上下文都不包含任何与用户需求相关的结构化信息**时，才可以输出“未找到相关数据”。

【输出要求】：
1. 若用户要求“提取”或“JSON”，请输出标准 JSON 数组，例如：
   [
     {{"字段1": "值1", "字段2": "值2"}},
     ...
   ]
   - 不要加 ```json 标记。
2. 若用户要求“总结”或“概述”，请输出 Markdown 文本。
3. 不要编造网页中不存在的信息。如果字段缺失，可以省略该字段，而不是胡乱填充。

请严格按照以上要求作答：
"""

        messages = [
            {"role": "system", "content": "你是一个擅长从混乱网页中提取结构化数据的 AI 专家。"},
            {"role": "user", "content": prompt},
        ]

        try:
            summary = await pangu_client.chat_completion(messages, temperature=0.1)
            logger.info("✅ Analysis completed.")
            return summary

        except Exception as e:
            logger.error(f"Analysis Failed: {e}")
            return f"AI 分析错误: {str(e)}"


result_analyzer = ResultAnalyzer()
