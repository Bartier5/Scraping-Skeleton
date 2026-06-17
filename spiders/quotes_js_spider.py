import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from spiders.base_spider import BaseSpider
from pipeline.cleaner import DataCleaner
from pipeline.transformer import DataTransformer
from pipeline.validator import DataValidator
from pipeline.validator import QuoteSchema
from utils.url_utils import prepare_urls
from utils.logger import log


class QuotesJsSpider(BaseSpider):
    """
    Scrapes quotes.toscrape.com/js — a JavaScript-rendered site.
    Uses BrowserFetcher (Playwright) instead of AsyncFetcher.
    Everything else — pipeline, storage, stats — is identical to ExampleSpider.
    """

    DEFAULT_URLS = [
        "https://quotes.toscrape.com/js/",
        "https://quotes.toscrape.com/js/page/2/",
        "https://quotes.toscrape.com/js/page/3/",
    ]

    def __init__(self, **kwargs):
        # Inject BrowserFetcher instead of the default AsyncFetcher
        from fetcher.browser_fetcher import BrowserFetcher
        browser_fetcher = BrowserFetcher()

        super().__init__(
            name="QuotesJsSpider",
            fetcher=browser_fetcher,   # ← the only real difference
            **kwargs
        )

        self._cleaner = DataCleaner()
        self._transformer = DataTransformer(add_metadata=True)
        self._validator = DataValidator(schema=QuoteSchema, strict=False)

    async def run(self, urls: list[str] = None, **kwargs) -> dict:
        urls = prepare_urls(urls or self.DEFAULT_URLS)
        self.start_run(urls)

        async with self:
            for url in urls:
                await self._scrape_page(url)

        self.finish_run()
        return self.get_stats()

    async def _scrape_page(self, url: str) -> int:
        log.info("QuotesJsSpider: scraping {}", url)

        result = await self.fetch(url)
        if result.failed:
            log.warning("QuotesJsSpider: fetch failed — {}", result.error)
            return 0

        # Same CSS selectors as the static version — JS rendered the same HTML
        soup = self.parser.make_soup(result.html)

        texts   = self.parser.get_all_text(soup, "span.text")
        authors = self.parser.get_all_text(soup, "small.author")
        tags_els = soup.select("div.tags a.tag")

        # Group tags per quote — each quote has multiple tags
        all_tag_groups = []
        for quote_el in soup.select("div.quote"):
            tag_els = quote_el.select("a.tag")
            all_tag_groups.append([t.get_text(strip=True) for t in tag_els])

        if not texts:
            log.warning("QuotesJsSpider: no quotes found — JS may not have rendered")
            return 0

        raw_items = []
        for i, (text, author) in enumerate(zip(texts, authors)):
            raw_items.append({
                "text":   text,
                "author": author,
                "tags":   all_tag_groups[i] if i < len(all_tag_groups) else [],
                "url":    url,
            })

        self._stats["items_scraped"] += len(raw_items)
        log.debug("QuotesJsSpider: parsed {} quotes from {}", len(raw_items), url)

        cleaned     = self._cleaner.clean_items(raw_items)
        transformed = self._transformer.transform_items(cleaned)
        batch       = self._validator.validate_batch(transformed)
        saved       = await self.save(batch.valid_items)

        log.info("QuotesJsSpider: {} quotes saved from {}", saved, url)
        return saved