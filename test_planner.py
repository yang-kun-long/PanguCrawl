import asyncio
import json
from app.services.planner import crawl_planner


async def main():
    # 测试案例：给一个模糊的需求，看盘古能不能自动补全 URL
    user_input = "我想爬取关于 DeepSeek 大模型的最新技术分析文章"

    print(f"用户输入: {user_input}")
    print("正在生成计划 (Waiting for Pangu)...")

    try:
        plan = await crawl_planner.generate_plan(user_input)

        print("\n=== 生成的爬取计划 (JSON) ===")
        print(json.dumps(plan, indent=2, ensure_ascii=False))
        print("============================")

        # 检查关键点
        if plan.get("seed_urls") and len(plan["seed_urls"]) > 0:
            print("✅ 成功生成了 Seed URLs")
        else:
            print("⚠️ 未生成 Seed URLs")

    except Exception as e:
        print(f"❌ 生成失败: {e}")


if __name__ == "__main__":
    asyncio.run(main())