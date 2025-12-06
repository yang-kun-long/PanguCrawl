import os
import asyncio
import httpx
import time
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 配置
BASE_URL = "https://api.siliconflow.cn/v1"
TEST_MODEL = "Qwen/Qwen2.5-7B-Instruct"  # 测试用的轻量模型


def load_keys():
    """从 .env 读取密钥池"""
    pool_str = os.getenv("SILICONFLOW_API_KEY_POOL", "")
    if not pool_str:
        # 尝试回退读取旧变量
        single_key = os.getenv("PANGU_API_KEY")
        if single_key:
            return [single_key]
        return []

    return [k.strip() for k in pool_str.split(",") if k.strip()]


async def check_single_key(index, api_key):
    """测试单个 Key 的连通性"""
    mask_key = f"...{api_key[-6:]}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": TEST_MODEL,
        "messages": [{"role": "user", "content": "hi"}],  # 极简请求
        "max_tokens": 5
    }

    start_time = time.time()
    result = {
        "id": index + 1,
        "key": mask_key,
        "status": "❓",
        "latency": "0s",
        "msg": ""
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.post(
                f"{BASE_URL}/chat/completions",
                json=payload,
                headers=headers
            )

            # 计算耗时
            elapsed = time.time() - start_time
            result["latency"] = f"{elapsed:.2f}s"

            if resp.status_code == 200:
                result["status"] = "✅ 正常"
                result["msg"] = "200 OK"
            elif resp.status_code == 429:
                result["status"] = "⚠️ 限流"
                result["msg"] = "429 Rate Limit"
            elif resp.status_code == 401:
                result["status"] = "❌ 无效"
                result["msg"] = "401 Unauthorized (Key错误)"
            elif resp.status_code == 503:
                result["status"] = "🚧 拥堵"
                result["msg"] = "503 Server Busy"
            else:
                result["status"] = f"❌ 错误 {resp.status_code}"
                try:
                    err_json = resp.json()
                    result["msg"] = err_json.get("message", resp.text)[:30]
                except:
                    result["msg"] = resp.text[:30]

        except Exception as e:
            result["status"] = "💥 异常"
            result["msg"] = str(e)[:30]

    return result


async def main():
    keys = load_keys()
    print(f"\n🔍 正在体检 {len(keys)} 个 API Key...\n")
    print(f"{'ID':<5} {'Key后缀':<10} {'状态':<10} {'耗时':<8} {'详细信息'}")
    print("-" * 60)

    # 并发测试所有 Key
    tasks = [check_single_key(i, k) for i, k in enumerate(keys)]
    results = await asyncio.gather(*tasks)

    # 打印结果
    success_count = 0
    for res in results:
        print(f"{res['id']:<5} {res['key']:<10} {res['status']:<10} {res['latency']:<8} {res['msg']}")
        if "正常" in res["status"]:
            success_count += 1

    print("-" * 60)
    print(f"\n📊 总结: {success_count}/{len(keys)} 个 Key 可用。")

    if success_count == 0:
        print("❌ 所有 Key 都挂了，请检查 .env 配置或网络连接！")
    elif success_count < len(keys):
        print("⚠️ 部分 Key 不可用，建议剔除无效 Key 以提升速度。")
    else:
        print("🎉 所有 Key 健康，您可以放心开启高并发！")


if __name__ == "__main__":
    asyncio.run(main())