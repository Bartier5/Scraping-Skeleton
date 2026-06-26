import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from spiders.base_spider import BaseSpider
from pipeline.cleaner import DataCleaner
from pipeline.transformer import DataTransformer
from pipeline.validator import DataValidator
from pydantic import BaseModel
from typing import Optional
from utils.logger import log


class AmazonProductSchema(BaseModel):
    title: str
    price: Optional[str] = ""
    rating: Optional[str] = ""
    reviews: Optional[str] = ""
    url: Optional[str] = ""


class AmazonSpider(BaseSpider):
    """
    Test 4A — Real e-commerce with anti-bot.
    Target: amazon.com/s?k=python+books

    Uses TlsFetcher (curl-cffi) to spoof Chrome's TLS fingerprint.
    Amazon blocks standard aiohttp/requests because the TLS handshake
    looks like a bot. curl-cffi impersonates a real browser at the
    TLS layer — same cipher suites, same extensions, same order.
    """

    SEARCH_URL = "https://www.amazon.com/s?k=python+books"
    MAX_PAGES = 3

    def __init__(self, **kwargs):
        super().__init__(name="AmazonSpider", **kwargs)
        self._cleaner = DataCleaner()
        self._transformer = DataTransformer(add_metadata=True)
        self._validator = DataValidator(schema=AmazonProductSchema, strict=False)
       

    async def run(self, urls=None, **kwargs):
        self.start_run([self.SEARCH_URL])

        async with self:
            for page in range(1, self.MAX_PAGES + 1):
                url = f"{self.SEARCH_URL}&page={page}"
                await self._scrape_page(url, page)

        self.finish_run()
        return self.get_stats()

    async def _scrape_page(self, url: str, page_num: int):
        log.info("AmazonSpider: fetching page {} — {}", page_num, url)

        from concurrent.futures import ThreadPoolExecutor

        def _run_sync():
            new_loop = asyncio.ProactorEventLoop()
            asyncio.set_event_loop(new_loop)
            try:
                return new_loop.run_until_complete(self._playwright_fetch(url))
            finally:
                new_loop.close()

        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            html = await loop.run_in_executor(pool, _run_sync)

        if not html:
            log.error("AmazonSpider: no HTML returned for page {}", page_num)
            return

        if "Robot Check" in html or "Enter the characters" in html:
            log.warning("AmazonSpider: CAPTCHA on page {}", page_num)
            return

        soup = self.parser.make_soup(html)
        cards = soup.select("div[data-component-type='s-search-result']")
        log.info("AmazonSpider: found {} product cards on page {}", len(cards), page_num)

        if not cards:
            log.warning("AmazonSpider: no cards — HTML preview: {}", html[:1000])
            return

        raw = []
        for card in cards:
            title_el  = card.select_one("h2 span")
            price_el  = card.select_one("span.a-price span.a-offscreen")
            rating_el = card.select_one("span.a-icon-alt")
            review_el = card.select_one("span.a-size-base.s-underline-text")
            link_el   = card.select_one("a.a-link-normal.s-no-outline")

            raw.append({
                "title":   title_el.get_text(strip=True) if title_el else "",
                "price":   price_el.get_text(strip=True) if price_el else "",
                "rating":  rating_el.get_text(strip=True) if rating_el else "",
                "reviews": review_el.get_text(strip=True) if review_el else "",
                "url":     "https://www.amazon.com" + link_el["href"] if link_el else "",
            })

        cleaned     = self._cleaner.clean_items(raw)
        transformed = self._transformer.transform_items(cleaned)
        batch       = self._validator.validate_batch(transformed)
        await self.save(batch.valid_items)

        self._stats["items_scraped"] += len(batch.valid_items)
        log.info("AmazonSpider: saved {} products from page {}", len(batch.valid_items), page_num)

    async def _playwright_fetch(self, url: str) -> str:
        from playwright.async_api import async_playwright

        html = ""
        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(
                    headless=False,  # visible browser — bypasses headless detection
                    args=["--no-sandbox", "--start-maximized"]
                )
                context = await browser.new_context(
                    viewport={"width": 1280, "height": 800},
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    locale="en-US",
                    timezone_id="America/New_York",
                )
                page = await context.new_page()

                # Remove webdriver flag — key headless signal
                await page.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
                )

                log.info("AmazonSpider: navigating to {}", url)
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)

                # Wait for JS challenge to resolve and redirect
                await asyncio.sleep(7)

                # Wait for actual product cards
                try:
                    await page.wait_for_selector(
                        "div[data-component-type='s-search-result']",
                        timeout=20000
                    )
                    log.info("AmazonSpider: product cards visible")
                except Exception:
                    log.warning("AmazonSpider: cards not found after wait")

                html = await page.content()
                await browser.close()

        except Exception as e:
            log.error("AmazonSpider._playwright_fetch failed: {}", str(e))

        return html