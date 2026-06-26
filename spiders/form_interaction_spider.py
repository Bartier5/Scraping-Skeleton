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
from utils.logger import log


class FormInteractionSpider(BaseSpider):
    """
    Test 3B — Form interaction / search.
    Target: quotes.toscrape.com/filter.aspx

    Strategy:
    1. Navigate to the filter page
    2. Read all available authors from the dropdown
    3. For each author — select author, select first tag, click Search
    4. Wait for results to load
    5. Parse quotes from results
    6. Repeat for all authors
    """

    TARGET_URL = "https://quotes.toscrape.com/filter.aspx"
    BASE_URL = "https://quotes.toscrape.com"

    def __init__(self, **kwargs):
        super().__init__(name="FormInteractionSpider", **kwargs)
        self._cleaner = DataCleaner()
        self._transformer = DataTransformer(add_metadata=True)
        self._validator = DataValidator(schema=QuoteSchema, strict=False)

    async def run(self, urls=None, **kwargs):
        self.start_run([self.TARGET_URL])

        async with self:
            await self._scrape_form()

        self.finish_run()
        return self.get_stats()

    async def _scrape_form(self):
        from concurrent.futures import ThreadPoolExecutor

        def _run_sync():
            new_loop = asyncio.ProactorEventLoop()
            asyncio.set_event_loop(new_loop)
            try:
                return new_loop.run_until_complete(self._playwright_form_fetch())
            finally:
                new_loop.close()

        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            all_items = await loop.run_in_executor(pool, _run_sync)

        if not all_items:
            log.error("FormInteractionSpider: no items returned")
            return

        cleaned     = self._cleaner.clean_items(all_items)
        transformed = self._transformer.transform_items(cleaned)
        batch       = self._validator.validate_batch(transformed)
        saved       = await self.save(batch.valid_items)

        self._stats["items_scraped"] += len(all_items)
        log.info("FormInteractionSpider: {} quotes saved", saved)

    async def _playwright_form_fetch(self) -> list:
        from playwright.async_api import async_playwright

        all_items = []

        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage"]
                )
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    )
                )
                page = await context.new_page()

                # Step 1 — Load the form page
                for attempt in range(1, 4):
                    try:
                        await page.goto(
                            self.TARGET_URL,
                            wait_until="domcontentloaded",
                            timeout=60000
                        )
                        await asyncio.sleep(3)
                        log.info("FormInteractionSpider: page loaded")
                        html_debug = await page.content()
                        log.info("FormInteractionSpider: HTML preview — {}", html_debug[:2000])
                        break
                    except Exception as e:
                        log.warning("FormInteractionSpider: goto attempt {} failed — {}", attempt, str(e))
                        if attempt == 3:
                            raise
                        await asyncio.sleep(3)

                # Step 2 — Read all authors from the dropdown
                await page.wait_for_selector("select#author", timeout=30000)
                authors = await page.eval_on_selector(
                    "select#author",
                    "el => Array.from(el.options).map(o => o.value).filter(v => v !== '')"
                )
                log.info("FormInteractionSpider: found {} authors", len(authors))

                # Step 3 — Loop through each author
                for author in authors:
                    log.info("FormInteractionSpider: searching author — {}", author)

                    # Select author
                    await page.select_option("select#author", author)
                    await page.wait_for_load_state("networkidle", timeout=15000)
                    await asyncio.sleep(1)

                    # Read available tags for this author
                    tags = await page.eval_on_selector(
                        "select#tag",
                        "el => Array.from(el.options).map(o => o.value).filter(v => v !== '')"
                    )

                    if not tags:
                        log.warning("FormInteractionSpider: no tags for {} — skipping", author)
                        continue

                    # Select first tag
                    await page.select_option("select#tag", tags[0])
                    await asyncio.sleep(0.5)

                    # Click search
                    await page.click("input[type='submit']")
                    await page.wait_for_load_state("networkidle", timeout=15000)

                    # Step 4 — Parse results
                    html = await page.content()
                    from parser.bs4_parser import BS4Parser
                    parser = BS4Parser()
                    soup = parser.make_soup(html)

                    quote_els = soup.select("div.quote")
                    for q in quote_els:
                        text   = q.select_one("span.small") or q.select_one("span")
                        author_el = q.select_one("small.author") or q.select_one("span small")
                        quote_tags = [t.get_text(strip=True) for t in q.select("a.tag")]

                        all_items.append({
                            "text":   q.get_text(strip=True),
                            "author": author,
                            "tags":   ", ".join(quote_tags),
                            "url":    self.TARGET_URL,
                        })

                    log.info("FormInteractionSpider: {} quotes for author {}", len(quote_els), author)

                    # Go back to form for next author
                    await page.goto(self.TARGET_URL, wait_until="domcontentloaded", timeout=30000)
                    await asyncio.sleep(2)

                await browser.close()

        except Exception as e:
            log.error("FormInteractionSpider._playwright_form_fetch failed: {}", str(e))

        return all_items