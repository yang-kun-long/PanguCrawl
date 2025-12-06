# app/models.py
from datetime import datetime
from typing import Optional, Any
from sqlalchemy import String, DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# 1. 定义基类
class Base(DeclarativeBase):
    pass


# 2. 爬取任务表 (Task)
# 记录用户最初的请求和任务整体状态
class CrawlTask(Base):
    __tablename__ = "crawl_tasks"

    id: Mapped[str] = mapped_column(String, primary_key=True, comment="任务UUID")
    user_request: Mapped[str] = mapped_column(Text, comment="用户的原始自然语言需求")
    mode: Mapped[str] = mapped_column(String(20), default="topic", comment="模式: topic/url")
    status: Mapped[str] = mapped_column(String(20), default="PENDING", comment="PENDING, RUNNING, COMPLETED, FAILED")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    # 关联关系
    plan: Mapped["CrawlPlan"] = relationship(back_populates="task", uselist=False)
    results: Mapped[list["PageResult"]] = relationship(back_populates="task")


# 3. 爬取计划表 (Plan)
# 存储 LLM (盘古) 分析后生成的具体执行计划
class CrawlPlan(Base):
    __tablename__ = "crawl_plans"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("crawl_tasks.id"))

    # 核心：使用 JSONB 存储灵活的计划配置
    # 包含: seed_urls, max_depth, inclusion_rules, search_queries 等
    plan_data: Mapped[dict[str, Any]] = mapped_column(JSONB, comment="LLM生成的完整JSON计划")

    llm_raw_response: Mapped[Optional[str]] = mapped_column(Text, comment="LLM原始返回内容，用于Debug")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    task: Mapped["CrawlTask"] = relationship(back_populates="plan")


# 4. 页面结果表 (Result)
# 存储每一个 URL 的抓取结果
class PageResult(Base):
    __tablename__ = "page_results"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("crawl_tasks.id"))

    url: Mapped[str] = mapped_column(String, index=True)
    title: Mapped[Optional[str]] = mapped_column(String)

    # 内容存储
    markdown_content: Mapped[Optional[str]] = mapped_column(Text, comment="清洗后的Markdown")
    html_snapshot: Mapped[Optional[str]] = mapped_column(Text, comment="原始HTML快照(可选)")

    # 核心：多模态信息存储
    # 结构示例: {"images": ["http..."], "videos": [], "meta": {"lang": "zh"}}
    media_info: Mapped[dict[str, Any]] = mapped_column(JSONB, default={}, comment="图片/视频/元数据集合")

    status_code: Mapped[int] = mapped_column(default=200)
    error_msg: Mapped[Optional[str]] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    task: Mapped["CrawlTask"] = relationship(back_populates="results")