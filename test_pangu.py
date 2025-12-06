import asyncio
from app.services.llm import pangu_client


async def main():
    print("正在测试盘古连接...")
    messages = [
        {"role": "system", "content": "你是一个乐于助人的AI助手。"},
        {"role": "user", "content": "你好，请用一句话介绍你自己。"}
    ]

    try:
        reply = await pangu_client.chat_completion(messages)
        print("\n=== 盘古回复 ===")
        print(reply)
        print("==================")
        print("测试成功！")
    except Exception as e:
        print(f"\n测试失败: {e}")


if __name__ == "__main__":
    asyncio.run(main())