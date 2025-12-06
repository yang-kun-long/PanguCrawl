# app/services/crawler.py
import logging
import asyncio
from typing import Dict, Any, List
from crawl4ai import AsyncWebCrawler
from bs4 import BeautifulSoup, Comment
from urllib.parse import urljoin, urlparse
import html2text
import asyncio

logger = logging.getLogger(__name__)


class CrawlerService:
    def __init__(self):
        self.headless = True
        self.converter = html2text.HTML2Text()
        self.converter.ignore_links = False
        self.converter.ignore_images = False
        self.converter.body_width = 0
        self.semaphore = asyncio.Semaphore(10)

    def _clean_html(self, html_content: str) -> str:
        if not html_content: return ""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            for tag in soup(['script', 'style', 'noscript', 'iframe', 'svg', 'meta', 'link']):
                tag.decompose()
            for comment in soup.find_all(text=lambda text: isinstance(text, Comment)):
                comment.extract()
            return str(soup)
        except:
            return html_content

    async def crawl_single_page(self, url: str) -> Dict[str, Any]:
        # ✅ 加了这行限制并发
        async with self.semaphore:
            logger.info(f"🚀 Crawling: {url}")
            try:
                # 💡 每次创建新的 crawler 实例开销较大，
                # 其实 crawl4ai 支持复用 browser context，但为求稳先只加信号量
                async with AsyncWebCrawler(verbose=False, headless=self.headless) as crawler:
                    result = await crawler.arun(url=url, bypass_cache=True)

                    if not result.success:
                        return self._error_response(url, result.error_message)

                    raw_html = str(result.html) if result.html else ""
                    cleaned_html = self._clean_html(raw_html)
                    markdown_content = self.converter.handle(cleaned_html)

                    # 强制绝对路径逻辑 (保持你刚才修改的)
                    soup = BeautifulSoup(cleaned_html, 'html.parser')
                    extracted_links = []
                    seen_urls = set()
                    base_url = result.url if result.url else url
                    base_domain = urlparse(base_url).netloc

                    for tag in soup.find_all('a', href=True):
                        href = tag.get('href', '').strip()
                        text = tag.get_text(strip=True)
                        if not href or len(text) < 1: continue
                        if href.startswith(('javascript:', '#', 'mailto:')): continue
                        try:
                            full_url = urljoin(base_url, href)
                            if base_domain in full_url and full_url not in seen_urls:
                                seen_urls.add(full_url)
                                extracted_links.append({"url": full_url, "text": text})
                        except:
                            continue

                    logger.info(f"✅ Success: {url} | Found {len(extracted_links)} links")

                    return {
                        "url": url,
                        "title": "Page Title",
                        "markdown_content": markdown_content,
                        "media_info": {"links": extracted_links},
                        "status_code": 200,
                        "error_msg": None
                    }

            except Exception as e:
                logger.error(f"💥 Error processing {url}: {str(e)}")
                return self._error_response(url, str(e))

    async def crawl_multiple(self, urls: List[str]) -> List[Dict[str, Any]]:
        # 这里不需要变，因为 tasks 里的每一个任务都会被 crawl_single_page 里的 semaphore 卡住
        return await asyncio.gather(*[self.crawl_single_page(u) for u in urls])

    def _error_response(self, url, msg):
        return {
            "url": url, "status_code": 0, "error_msg": str(msg),
            "markdown_content": "", "media_info": {"links": []}
        }



crawler_service = CrawlerService()