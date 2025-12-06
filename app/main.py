# app/main.py
import sys
import asyncio
import uuid
import logging
import heapq  # 用于优先级队列 (Best-First Search)
from typing import List, Optional, Set  # Set 用于去重
import json # 用于 JSON 数据的处理
from app.services.template_scorer import score_page_results_for_task

from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from fastapi.openapi.docs import get_swagger_ui_html
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.services.structure_scorer import score_task_structure
from app.services.schema_discovery import schema_discovery
from app.services.extractor import structured_extractor
from sqlalchemy.orm.attributes import flag_modified

# --- Windows 异步循环修正 (防止 Playwright 报错) ---
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


# --- 🚀 核心工作流：多 AI 协同分层决策 ---
async def run_smart_crawl(task_id: str, user_request: str, db: Session):
    logger.info(f"Task {task_id}: AI-Guided Layered Crawl started.")

    try:
        # 1. 初始化
        plan_json = await crawl_planner.generate_plan(user_request)
        db.query(CrawlPlan).filter(CrawlPlan.task_id == task_id).delete(synchronize_session=False)
        db.flush()

        new_plan = CrawlPlan(
            id=str(uuid.uuid4()), task_id=task_id, plan_data=plan_json, llm_raw_response=str(plan_json)
        )
        db.add(new_plan)
        task = db.query(CrawlTask).filter(CrawlTask.id == task_id).first()
        task.status = "RUNNING"
        db.commit()

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

            # 更新 DB，前端可以看到分层进度
            status_msg = f"\n\n🔶 === 进入第 {depth} 层 (待爬: {len(current_layer_urls)} 个) ==="
            full_debate_log += status_msg
            task.plan.plan_data["debate_logs"] = full_debate_log
            flag_modified(task.plan, "plan_data")
            db.commit()

            # 1. 爬取当前层
            batch_results = await crawler_service.crawl_multiple(current_layer_urls)
            candidates = []

            for res in batch_results:
                url = res['url']
                visited_urls.add(url)
                crawled_count += 1

                # 页面入库
                page_result = PageResult(
                    task_id=task_id, url=url,
                    title=res.get('title'), markdown_content=res.get('markdown_content'),
                    media_info=res.get('media_info', {}),
                    status_code=res.get('status_code', 0), error_msg=res.get('error_msg')
                )
                db.add(page_result)
                task = db.query(CrawlTask).filter(CrawlTask.id == task_id).first()
                task.plan.plan_data["crawled_count"] = crawled_count
                task.plan.plan_data["total_estimated"] = max_pages
                flag_modified(task.plan, "plan_data")
                # 实时提交 (确保前端能马上看到)
                db.commit()
                # 收集新链接
                if res.get('status_code') == 200:
                    page_links = res.get('media_info', {}).get('links', [])
                    for link in page_links:
                        if link['url'] not in visited_urls:
                            candidates.append(link)

            db.commit() # 提交本层爬取结果

            # 2. 召开分批 AI 会议，决定下一层
            if depth < max_depth - 1:
                if not candidates:
                    full_debate_log += "\n[系统]: 本层未发现新链接，探索结束。"
                    break

                unique_candidates = list({v['url']: v for v in candidates}.values())

                # --- 🔥 实时接收 AI 委员会辩论 ---
                full_debate_log += f"\n[系统]: 发现 {len(unique_candidates)} 个候选，AI 委员会正在接入..."

                next_layer_candidates = []

                async for chunk in crawl_planner.run_debate_stream(
                        user_request, f"Layer {depth}", unique_candidates
                ):
                    speaker = chunk["role"]
                    content = chunk["content"]

                    # 格式优化：让每轮对话看起来更清晰
                    if speaker == "系统":
                        log_entry = f"\n\n🔧 **[{speaker}]**: {content}"
                    else:
                        log_entry = f"\n> **{speaker}**: {content}"

                    full_debate_log += log_entry

                    # 实时写入 DB
                    task = db.query(CrawlTask).filter(CrawlTask.id == task_id).first()
                    task.plan.plan_data["debate_logs"] = full_debate_log
                    flag_modified(task.plan, "plan_data")
                    db.commit()

                    if "final_result" in chunk:
                        next_layer_candidates.extend(chunk["final_result"])

                # 更新下一层 URL
                current_layer_urls = [u for u in next_layer_candidates if u not in visited_urls]
        logger.info(f"Task {task_id}: Scoring structure across pages...")
        score_task_structure(task_id, db)
        # --- 2) AI 生成模板 + 本地抽取 ---
        logger.info(f"Task {task_id}: Discovering schemas...")
        schemas = await schema_discovery.discover_for_task(task_id, db)
        logger.info(f"Task {task_id}: Schemas count = {len(schemas)}")

        logger.info(f"Task {task_id}: Running local structured extraction...")
        extract_result = await structured_extractor.extract_for_task_async(task_id, db, schemas)

        # 可以顺手把结果塞进 plan_data，前端想看就直接读这里
        task = db.query(CrawlTask).filter(CrawlTask.id == task_id).first()
        if task and task.plan:
            data = task.plan.plan_data or {}
            data["structured_extract"] = extract_result
            task.plan.plan_data = data
            flag_modified(task.plan, "plan_data")
            db.commit()
        # --- 最终分析 ---
        logger.info(f"Task {task_id}: Starting Final Analysis...")
        summary = await result_analyzer.analyze_task(task_id, db)

        # 将总结写入 Plan
        task = db.query(CrawlTask).filter(CrawlTask.id == task_id).first()
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


@app.post("/tasks", response_model=TaskResponse)
async def create_task(req: TaskRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    task_id = str(uuid.uuid4())
    new_task = CrawlTask(id=task_id, user_request=req.user_request, mode=req.mode, status="PENDING")
    # 初始化 Plan，避免 JSONB 访问 None
    new_task.plan = CrawlPlan(id=str(uuid.uuid4()), task_id=task_id, plan_data={"debate_logs": "正在初始化会议..."})
    db.add(new_task)
    db.commit()
    background_tasks.add_task(run_smart_crawl, task_id, req.user_request, SessionLocal())
    return {"task_id": task_id, "status": "PENDING"}


@app.get("/tasks/{task_id}")
def get_task_status(task_id: str, db: Session = Depends(get_db)):
    task = db.query(CrawlTask).filter(CrawlTask.id == task_id).first()
    if not task: raise HTTPException(status_code=404, detail="Task not found")

    results_data = []
    # 限制返回列表长度，防止前端太卡，只返回元数据，详情按需加载(优化点)
    # 但为了简单，这里还是先全量返回，但要注意性能
    for r in task.results:
        results_data.append({
            "url": r.url, "title": r.title, "status_code": r.status_code,
            "media_info": r.media_info, "markdown_content": r.markdown_content,
            "error_msg": r.error_msg
        })

    # 从 plan_data 提取日志、总结、以及最重要的结构化数据
    ai_summary = ""
    debate_logs = ""
    crawled_count = 0
    total_estimated = 0
    structured_data = None  # 🟢 [新增] 结构化数据容器

    if task.plan and task.plan.plan_data:
        data = task.plan.plan_data
        ai_summary = data.get("final_summary", "")
        debate_logs = data.get("debate_logs", "")
        crawled_count = data.get("crawled_count", 0)
        total_estimated = data.get("total_estimated", 0)
        # 🟢 [新增] 读取提取结果
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
        "structured_data": structured_data # 🟢 [新增] 返回给前端
    }