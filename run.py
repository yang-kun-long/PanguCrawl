# run.py
import uvicorn
import logging
import sys
import asyncio

# --- 定义日志过滤器 ---
class EndpointFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # 屏蔽所有包含 /tasks/ 的日志，彻底解决前端轮询刷屏问题
        return "/tasks/" not in record.getMessage()

def main():
    # 1. 强制配置 Windows 异步策略 (解决 Playwright 报错)
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    # 2. 获取 uvicorn 的访问日志记录器
    # 注意：必须在 run 之前获取，否则会被覆盖
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.addFilter(EndpointFilter())

    print("🚀 服务已启动! (已屏蔽前端轮询日志，只显示关键信息)")
    print("👉 API 文档: http://127.0.0.1:8001/docs")

    # 3. 启动服务
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8001,
        reload=False, # 设为 False 避免 Windows 下 Loop 冲突
        log_level="info"
    )

if __name__ == "__main__":
    main()