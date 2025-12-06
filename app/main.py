import sys
import asyncio
import uuid
import logging
import heapq
from typing import List, Optional, Set
import json
# from app.services.template_scorer import score_page_results_for_task # 移除废弃引用

from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from fastapi.openapi.docs import get_swagger_ui_html
from sqlalchemy.orm import Session
from sqlalchemy import desc
from pydantic import BaseModel
from app.services.structure_scorer import score_task_structure
from app.services.schema_discovery import schema_discovery
from app.services.extractor import structured_extractor
from sqlalchemy.orm.attributes import flag_modified

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from app.database import get_db, SessionLocal
from app.models import CrawlTask, CrawlPlan, PageResult
from app.services.planner import crawl_planner
from app.services.crawler import crawler_service
from app.services.analyzer import result_analyzer
from app.utils import cluster_links

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Deep Web Crawler API", version="0.7", docs_url=None, redoc_url="/redoc")


@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html():
    return get_swagger_ui_html(
        openapi_url=app.openapi_url, title=app.title, oauth2_redirect_url=app.swagger_ui_oauth2_redirect_url
    )


class TaskRequest(BaseModel):
    user_request: str
    mode: str = "topic"


class TaskResponse(BaseModel):
    task_id: str
    status: str


# 🟢 [新增] 历史任务列表响应模型
class TaskSummary(BaseModel):
    id: str
    user_request: str
    status: str
    created_at: str
    mode: str


# --- 🚀 核心工作流 (保持不变) ---
async def run_smart_crawl(task_id: str, user_request: str, db: Session):
    logger.info(f"Task {task_id}: AI-Guided Layered Crawl started.")
    try:
        # 1. 生成计划
        plan_json = await crawl_planner.generate_plan(user_request)

        # 清除旧计划（如果这是一个重试任务），但保留任务记录本身
        db.query(CrawlPlan).filter(CrawlPlan.task_id == task_id).delete(synchronize_session=False)
        db.flush()

        new_plan = CrawlPlan(
            id=str(uuid.uuid4()), task_id=task_id, plan_data=plan_json, llm_raw_response=str(plan_json)
        )
        db.add(new_plan)

        task = db.query(CrawlTask).filter(CrawlTask.id == task_id).first()
        task.status = "RUNNING"
        db.commit()

        # ... (后续爬取、分析、提取逻辑保持完全一致，此处省略以节省篇幅) ...
        # (请保留你原来 run_smart_crawl 的完整逻辑，不要删除)

        # 配置参数
        max_depth = plan_json.get("max_depth", 2)
        max_pages = plan_json.get("max_pages", 15)
        current_layer_urls = plan_json.get("seed_urls", [])
        visited_urls = set()
        crawled_count = 0
        full_debate_log = ""

        # --- 分层循环 ---
        for depth in range(max_depth):
            if not current_layer_urls or crawled_count >= max_pages: break

            status_msg = f"\n\n🔶 === 进入第 {depth} 层 (待爬: {len(current_layer_urls)} 个) ==="
            full_debate_log += status_msg
            task.plan.plan_data["debate_logs"] = full_debate_log
            flag_modified(task.plan, "plan_data")
            db.commit()

            # 爬取
            batch_results = await crawler_service.crawl_multiple(current_layer_urls)
            candidates = []

            for res in batch_results:
                url = res['url']
                visited_urls.add(url)
                crawled_count += 1

                page_result = PageResult(
                    task_id=task_id, url=url,
                    title=res.get('title'), markdown_content=res.get('markdown_content'),
                    media_info=res.get('media_info', {}),
                    status_code=res.get('status_code', 0), error_msg=res.get('error_msg')
                )
                db.add(page_result)
                task.plan.plan_data["crawled_count"] = crawled_count
                task.plan.plan_data["total_estimated"] = max_pages
                flag_modified(task.plan, "plan_data")
                db.commit()

                if res.get('status_code') == 200:
                    page_links = res.get('media_info', {}).get('links', [])
                    for link in page_links:
                        if link['url'] not in visited_urls:
                            candidates.append(link)
            db.commit()

            # AI 会议
            if depth < max_depth - 1:
                if not candidates:
                    full_debate_log += "\n[系统]: 本层未发现新链接，探索结束。"
                    break
                unique_candidates = list({v['url']: v for v in candidates}.values())
                full_debate_log += f"\n[系统]: 发现 {len(unique_candidates)} 个候选，AI 委员会正在接入..."
                next_layer_candidates = []
                async for chunk in crawl_planner.run_debate_stream(
                        user_request, f"Layer {depth}", unique_candidates
                ):
                    speaker = chunk["role"]
                    content = chunk["content"]
                    if speaker == "系统":
                        log_entry = f"\n\n🔧 **[{speaker}]**: {content}"
                    else:
                        log_entry = f"\n> **{speaker}**: {content}"
                    full_debate_log += log_entry
                    task.plan.plan_data["debate_logs"] = full_debate_log
                    flag_modified(task.plan, "plan_data")
                    db.commit()
                    if "final_result" in chunk:
                        next_layer_candidates.extend(chunk["final_result"])
                current_layer_urls = [u for u in next_layer_candidates if u not in visited_urls]

        # 结构化评分
        logger.info(f"Task {task_id}: Scoring structure across pages...")
        score_task_structure(task_id, db)

        # Schema 发现
        logger.info(f"Task {task_id}: Discovering schemas...")
        schemas = await schema_discovery.discover_for_task(task_id, db)

        # 结构化提取
        logger.info(f"Task {task_id}: Running local structured extraction...")
        extract_result = await structured_extractor.extract_for_task_async(task_id, db, schemas)
        if task.plan:
            data = task.plan.plan_data or {}
            data["structured_extract"] = extract_result
            task.plan.plan_data = data
            flag_modified(task.plan, "plan_data")
            db.commit()

        # 最终分析
        logger.info(f"Task {task_id}: Starting Final Analysis...")
        summary = await result_analyzer.analyze_task(task_id, db)
        task.plan.plan_data["final_summary"] = summary
        flag_modified(task.plan, "plan_data")

        task.status = "COMPLETED"
        db.commit()
        logger.info(f"Task {task_id}: Workflow completed.")

    except Exception as e:
        logger.error(f"Task Failed: {e}")
        try:
            task = db.query(CrawlTask).filter(CrawlTask.id == task_id).first()
            task.status = "FAILED"
            db.commit()
        except:
            pass
    finally:
        db.close()


# 🟢 [修改] 移除可能存在的清空逻辑，仅创建新任务
@app.post("/tasks", response_model=TaskResponse)
async def create_task(req: TaskRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    # 注意：这里我们生成一个新的 UUID，所以天然支持历史记录，不会覆盖旧任务
    task_id = str(uuid.uuid4())
    new_task = CrawlTask(id=task_id, user_request=req.user_request, mode=req.mode, status="PENDING")

    # 初始化 Plan
    new_task.plan = CrawlPlan(id=str(uuid.uuid4()), task_id=task_id, plan_data={"debate_logs": "正在初始化会议..."})

    db.add(new_task)
    db.commit()

    # 单例运行模式：如果你想限制并发，可以在这里检查是否有正在运行的任务
    # 但为了简单，我们还是允许触发，靠 Extractor 的信号量去控制速率
    background_tasks.add_task(run_smart_crawl, task_id, req.user_request, SessionLocal())

    return {"task_id": task_id, "status": "PENDING"}


# 🟢 [新增] 获取历史任务列表
@app.get("/tasks", response_model=List[TaskSummary])
def get_all_tasks(db: Session = Depends(get_db)):
    # 按时间倒序，最近的在前面
    tasks = db.query(CrawlTask).order_by(desc(CrawlTask.created_at)).limit(50).all()
    return [
        {
            "id": t.id,
            "user_request": t.user_request[:50] + "..." if len(t.user_request) > 50 else t.user_request,
            "status": t.status,
            "created_at": t.created_at.strftime("%Y-%m-%d %H:%M:%S") if t.created_at else "",
            "mode": t.mode
        }
        for t in tasks
    ]


@app.get("/tasks/{task_id}")
def get_task_status(task_id: str, db: Session = Depends(get_db)):
    task = db.query(CrawlTask).filter(CrawlTask.id == task_id).first()
    if not task: raise HTTPException(status_code=404, detail="Task not found")

    results_data = []
    # 仅返回必要字段，减轻前端压力
    for r in task.results:
        results_data.append({
            "url": r.url,
            "title": r.title,
            "status_code": r.status_code,
            "media_info": r.media_info,
            "markdown_content": r.markdown_content,
            "error_msg": r.error_msg
        })

    ai_summary = ""
    debate_logs = ""
    crawled_count = 0
    total_estimated = 0
    structured_data = None

    if task.plan and task.plan.plan_data:
        data = task.plan.plan_data
        ai_summary = data.get("final_summary", "")
        debate_logs = data.get("debate_logs", "")
        crawled_count = data.get("crawled_count", 0)
        total_estimated = data.get("total_estimated", 0)
        structured_data = data.get("structured_extract", None)

    return {
        "id": task.id,
        "status": task.status,
        "results_count": len(task.results),
        "results": results_data,
        "summary": ai_summary,
        "debate_logs": debate_logs,
        "crawled_count": crawled_count,
        "total_estimated": total_estimated,
        "structured_data": structured_data
    }