import asyncio
import json
from app.services.crawler import crawler_service


async def main():
    # 测试目标：抓取一个简单的页面，比如 DeepSeek 官网或者一篇技术博客
    # 这里用一个比较稳定的技术博客 URL，或者学校官网
    test_url = "https://www.bit.edu.cn"

    print(f"正在尝试抓取: {test_url}")

    try:
        result = await crawler_service.crawl_single_page(test_url)

        print("\n=== 抓取结果概览 ===")
        print(f"URL: {result['url']}")
        print(f"状态: {result.get('status_code')}")
        print(f"Markdown 长度: {len(result.get('markdown_content', ''))}")

        # 打印前 200 个字符的 Markdown 看看清洗效果
        print("\n--- Markdown Preview ---")
        print(result.get('markdown_content', '')[:200])
        print("------------------------")

        print(f"发现图片数量: {len(result['media_info']['images'])}")
        print(f"发现内部链接: {len(result['media_info']['internal_links'])}")

    except Exception as e:
        print(f"❌ 抓取测试失败: {e}")


if __name__ == "__main__":
    asyncio.run(main())