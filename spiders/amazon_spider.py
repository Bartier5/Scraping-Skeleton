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
from anti_bot.fingerprint_manager import TlsFetcher
from anti_bot.headers_manager import HeadersManager
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
        self._tls = TlsFetcher(browser="chrome120")
        self._headers = HeadersManager(browser="chrome").get_headers(
            url=self.SEARCH_URL
        )

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

        # TlsFetcher is sync — run in executor to avoid blocking event loop
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self._tls.fetch(url, headers=self._headers)
        )

        status = result.get("status_code")
        html = result.get("html", "")
        error = result.get("error")

        if error or not html:
            log.error("AmazonSpider: failed page {} — {}", page_num, error)
            return

        if status != 200:
            log.warning("AmazonSpider: status {} on page {}", status, page_num)

        if "Enter the characters you see below" in html or "Robot Check" in html:
            log.warning("AmazonSpider: CAPTCHA detected on page {}", page_num)
            return

        # Parse HTML
        soup = self.parser.make_soup(html)

        # Amazon product cards
        cards = soup.select("div[data-component-type='s-search-result']")
        log.info("AmazonSpider: found {} product cards on page {}", len(cards), page_num)

        if not cards:
            # Dump first 1000 chars to debug
            log.warning("AmazonSpider: no cards found — HTML preview: {}", html[:1000])
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