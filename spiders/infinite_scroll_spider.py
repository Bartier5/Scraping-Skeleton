# ── spiders/infinite_scroll_spider.py ────────────────────────────────────────
# Test 2A — Infinite scroll spider.
# Target: quotes.toscrape.com/scroll
#
# What makes this different from QuotesJsSpider:
#   The page loads 10 quotes on first render. When you scroll to the bottom,
#   an AJAX request fires and injects 10 more quotes into the DOM.
#   There is no "next page" URL — it's all one page, one URL.
#   A standard goto() + page.content() only gets the first 10.
#   We need to scroll repeatedly until no new content loads.
#
# The scroll pattern used here applies to:
#   - Twitter/X timelines
#   - LinkedIn job listings
#   - Instagram feeds
#   - Indeed search results
#   - Any site with "load more as you scroll" behavior

import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from spiders.base_spider import BaseSpider
from pipeline.cleaner import DataCleaner
from pipeline.transformer import DataTransformer
from pipeline.validator import DataValidator, QuoteSchema
from utils.url_utils import prepare_urls
from utils.logger import log


class InfiniteScrollSpider(BaseSpider):
    """
    Scrapes quotes.toscrape.com/scroll — infinite scroll demo.

    Strategy:
    1. Navigate to the page
    2. Count quotes currently visible
    3. Scroll to the bottom via JavaScript
    4. Wait for new quotes to appear
    5. Count again — if count increased, repeat from step 3
    6. If count hasn't changed after scroll, we've hit the end
    7. Capture final HTML and parse all quotes
    """

    TARGET_URL = "https://quotes.toscrape.com/scroll"

    def __init__(self, max_scrolls: int = 20, **kwargs):
        # Don't inject BrowserFetcher — this spider runs Playwright directly
        super().__init__(name="InfiniteScrollSpider", **kwargs)

        self.max_scrolls = max_scrolls
        self._cleaner = DataCleaner()
        self._transformer = DataTransformer(add_metadata=True)
        self._validator = DataValidator(schema=QuoteSchema, strict=False)

        log.debug("InfiniteScrollSpider: max_scrolls={}", max_scrolls)

    async def run(self, urls: list[str] = None, **kwargs) -> dict:
        urls = [self.TARGET_URL]
        self.start_run(urls)

        async with self:
            await self._scrape_infinite_scroll()

        self.finish_run()
        return self.get_stats()

    async def _scrape_infinite_scroll(self) -> int:
        log.info("InfiniteScrollSpider: starting infinite scroll on {}", self.TARGET_URL)

        # Use the thread-based Playwright approach directly
        # (same ProactorEventLoop trick as BrowserFetcher)
        from concurrent.futures import ThreadPoolExecutor

        def _run_sync():
            new_loop = asyncio.ProactorEventLoop()
            asyncio.set_event_loop(new_loop)
            try:
                return new_loop.run_until_complete(self._playwright_scroll_fetch())
            finally:
                new_loop.close()

        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            html = await loop.run_in_executor(pool, _run_sync)

        if not html:
            log.error("InfiniteScrollSpider: got no HTML")
            return 0

        # Parse everything in one shot — all quotes are in the final HTML
        soup = self.parser.make_soup(html)

        texts   = self.parser.get_all_text(soup, "span.text")
        authors = self.parser.get_all_text(soup, "small.author")

        # Tags per quote
        all_tag_groups = []
        for quote_el in soup.select("div.quote"):
            tags = [t.get_text(strip=True) for t in quote_el.select("a.tag")]
            all_tag_groups.append(tags)

        if not texts:
            log.warning("InfiniteScrollSpider: no quotes found in final HTML")
            return 0

        raw_items = []
        for i, (text, author) in enumerate(zip(texts, authors)):
            raw_items.append({
                "text":   text,
                "author": author,
                "tags":   all_tag_groups[i] if i < len(all_tag_groups) else [],
                "url":    self.TARGET_URL,
            })

        self._stats["items_scraped"] += len(raw_items)
        log.info("InfiniteScrollSpider: parsed {} quotes total", len(raw_items))

        cleaned     = self._cleaner.clean_items(raw_items)
        transformed = self._transformer.transform_items(cleaned)
        batch       = self._validator.validate_batch(transformed)
        saved       = await self.save(batch.valid_items)

        log.info("InfiniteScrollSpider: {} quotes saved", saved)
        return saved

    async def _playwright_scroll_fetch(self) -> str:
        from playwright.async_api import async_playwright

        html = ""

        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage"]
                )
                context = await browser.new_context(
                    ignore_https_errors=True,
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    )
                )
                page = await context.new_page()

                # Retry goto up to 3 times — ERR_ABORTED can be transient
                for attempt in range(1, 4):
                    try:
                        log.info(
                            "InfiniteScrollSpider: loading page (attempt {}/3)...",
                            attempt
                        )
                        await page.goto(
                            self.TARGET_URL,
                            wait_until="domcontentloaded",
                            timeout=60000,
                        )
                        log.info("InfiniteScrollSpider: page loaded")
                        break
                    except Exception as e:
                        log.warning(
                            "InfiniteScrollSpider: goto attempt {} failed — {}",
                            attempt, str(e)
                        )
                        if attempt == 3:
                            raise
                        await asyncio.sleep(3)

                # Wait for JS to fire first render
                await asyncio.sleep(4)

                # Wait for quotes — non-fatal
                try:
                    await page.wait_for_selector("div.quote", timeout=30000)
                    log.info("InfiniteScrollSpider: first quotes visible")
                except Exception:
                    log.warning("InfiniteScrollSpider: selector timeout — proceeding anyway")

                # Scroll loop
                scroll_count = 0
                previous_count = 0

                while scroll_count < self.max_scrolls:
                    current_count = await page.eval_on_selector_all(
                        "div.quote",
                        "elements => elements.length"
                    )

                    log.info(
                        "InfiniteScrollSpider: scroll {}/{} — {} quotes visible",
                        scroll_count, self.max_scrolls, current_count
                    )

                    if scroll_count > 0 and current_count == previous_count:
                        log.info(
                            "InfiniteScrollSpider: no new quotes — "
                            "reached end at {} quotes", current_count
                        )
                        break

                    previous_count = current_count

                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

                    try:
                        await page.wait_for_load_state("networkidle", timeout=8000)
                    except Exception:
                        pass

                    await asyncio.sleep(1)
                    scroll_count += 1

                final_count = await page.eval_on_selector_all(
                    "div.quote", "elements => elements.length"
                )
                log.info(
                    "InfiniteScrollSpider: done — {} quotes, {} scrolls",
                    final_count, scroll_count
                )

                html = await page.content()
                await browser.close()

        except Exception as e:
            log.error("InfiniteScrollSpider._playwright_scroll_fetch failed: {}", str(e))

        return html