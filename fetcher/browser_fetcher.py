# ── fetcher/browser_fetcher.py ────────────────────────────────────────────────
# Browser-based fetcher using Playwright for JavaScript-heavy sites.
#
# When to use this fetcher:
#   - Sites that require JavaScript to render content
#   - Sites with heavy anti-bot protection (Cloudflare, PerimeterX)
#   - Single-page applications (React, Vue, Angular)
#   - Sites that check browser fingerprints
#
# When NOT to use this fetcher:
#   - Static HTML sites (use HttpFetcher or AsyncFetcher — much faster)
#   - Large batch jobs (browser is slow — max 3-5 parallel instances)
#
# How Playwright works:
#   Playwright controls a real Chromium browser programmatically.
#   It opens a browser, navigates to the URL, waits for JavaScript
#   to run and render the page, then returns the final HTML.
#   This is much slower than HTTP requests but produces the same result
#   a real user would see in their browser.
#
# Inherits from BaseFetcher.

import asyncio
from typing import Optional
from playwright.async_api import (
    async_playwright,       # async context manager that starts Playwright
    Browser,               # the browser instance (Chromium)
    BrowserContext,        # isolated browser session (like a fresh incognito window)
    Page,                  # a single browser tab
    TimeoutError as PlaywrightTimeout,  # page load timeout
    Error as PlaywrightError,           # general Playwright error
)

from fetcher.base_fetcher import BaseFetcher, FetchResult
from config.config import Config
from utils.logger import log
from utils.helpers import get_domain
from utils.rate_limiter import RateLimiter, default_limiter


class BrowserFetcher(BaseFetcher):
    """
    Playwright-based fetcher for JavaScript-heavy and anti-bot protected sites.

    Uses a persistent browser instance with a configurable number of
    parallel pages (tabs). Each fetch opens a new page, navigates to
    the URL, waits for the page to load, captures the HTML, then
    closes the page.

    Anti-bot evasion built in:
    - Realistic viewport size (1920x1080)
    - Real user agent string
    - JavaScript enabled (unlike requests/aiohttp)
    - Geolocation and timezone spoofing ready
    """

    # Realistic browser viewport — looks like a real desktop user
    DEFAULT_VIEWPORT = {"width": 1920, "height": 1080}

    # How long to wait for page to load before giving up (milliseconds)
    DEFAULT_TIMEOUT = Config.TIMEOUT * 1000   # convert seconds to ms

    def __init__(
        self,
        config: dict = None,
        headless: bool = True,          # True = invisible browser, False = visible window
        concurrency: int = 3,           # max parallel pages (tabs) open at once
        rate_limiter: RateLimiter = None,
        wait_until: str = "domcontentloaded",  # when to consider page "loaded"
    ):
        """
        Args:
            config:      optional config overrides
            headless:    True runs browser invisibly (production)
                         False shows the browser window (debugging)
            concurrency: max parallel browser tabs
                         Keep this low (2-5) — each tab uses significant RAM
            rate_limiter: per-domain rate limiter
            wait_until:  Playwright page load event to wait for:
                         "load"             → wait for all resources (images, css)
                         "domcontentloaded" → wait for HTML only (faster)
                         "networkidle"      → wait until no network activity (slowest)
        """
        super().__init__(config)

        self._headless = headless
        self._concurrency = concurrency
        self._semaphore = asyncio.Semaphore(concurrency)
        self._rate_limiter = rate_limiter or default_limiter
        self._wait_until = wait_until

        # Playwright objects — all None until first use (lazy init)
        self._playwright = None         # the Playwright instance
        self._browser: Optional[Browser] = None   # the Chromium browser

        log.debug(
            "BrowserFetcher initialized (headless={}, concurrency={}, wait_until={})",
            headless, concurrency, wait_until
        )

    async def _get_browser(self) -> Browser:
        """
        Returns the Playwright Browser instance, launching it if needed.
        Lazy initialization — browser only starts when first URL is fetched.
        """
        if self._browser is None or not self._browser.is_connected():
            # Start the Playwright engine
            self._playwright = await async_playwright().start()

            # Launch Chromium browser
            # chromium is the most compatible and best supported by Playwright
            self._browser = await self._playwright.chromium.launch(
                headless=self._headless,    # invisible or visible
                args=[
                    "--no-sandbox",                 # required in some environments
                    "--disable-blink-features=AutomationControlled",  # hide automation flag
                    "--disable-dev-shm-usage",      # prevents crashes in Docker/CI
                    "--disable-gpu",                # no GPU needed for headless
                ]
            )
            log.debug("BrowserFetcher: Chromium launched (headless={})", self._headless)

        return self._browser

    async def _new_context(self) -> BrowserContext:
        """
        Creates a fresh browser context (like a new incognito window).
        Each context is isolated — separate cookies, localStorage, sessions.
        This prevents cross-request contamination.
        """
        browser = await self._get_browser()

        context = await browser.new_context(
            viewport=self.DEFAULT_VIEWPORT,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            # These make the browser look more like a real user
            java_script_enabled=True,
            accept_downloads=False,     # we don't need file downloads
            ignore_https_errors=True,   # skip SSL errors (like aiohttp's ssl=False)
        )

        return context

    async def async_fetch(self, url: str, **kwargs) -> FetchResult:
        """
        Fetch a URL using a real Chromium browser tab.

        Flow:
        1. Rate limit check for this domain
        2. Acquire semaphore slot (max N tabs at once)
        3. Open fresh browser context + new page (tab)
        4. Navigate to URL and wait for page to load
        5. Capture full rendered HTML (after JavaScript runs)
        6. Close page and context
        7. Return FetchResult

        Args:
            url:       the URL to fetch
            **kwargs:  optional overrides:
                       - wait_until (str): override page load event
                       - timeout (int):   override timeout in ms
                       - wait_for (str):  CSS selector to wait for before capturing
                                          e.g. ".product-list" ensures products loaded

        Returns:
            FetchResult with rendered HTML
        """
        if not self.validate_url(url):
            return self.make_error_result(url, ValueError(f"Invalid URL: {url}"))

        domain = get_domain(url)
        wait_until = kwargs.get("wait_until", self._wait_until)
        timeout = kwargs.get("timeout", self.DEFAULT_TIMEOUT)
        wait_for_selector = kwargs.get("wait_for", None)

        # Rate limit per domain
        await self._rate_limiter.wait(domain)

        # Limit concurrent tabs
        async with self._semaphore:
            return await self._do_browser_fetch(
                url, wait_until, timeout, wait_for_selector
            )

    async def _do_browser_fetch(
        self,
        url: str,
        wait_until: str,
        timeout: int,
        wait_for_selector: Optional[str],
    ) -> FetchResult:
        """
        Internal method — performs the actual browser navigation and HTML capture.
        Creates a fresh context+page, navigates, captures, then closes everything.
        """
        context = None
        page = None

        try:
            # Fresh context for each request — clean cookies/session
            context = await self._new_context()
            page = await context.new_page()

            log.debug("BrowserFetcher navigating: {}", url)

            # Navigate to the URL — this is where JavaScript runs
            response = await page.goto(
                url,
                wait_until=wait_until,  # when to consider the page "done"
                timeout=timeout,        # max ms to wait
            )

            # If a specific element must be present before we capture
            # e.g. wait for product grid to load via AJAX
            if wait_for_selector:
                await page.wait_for_selector(
                    wait_for_selector,
                    timeout=timeout,
                )

            # page.content() returns the FULL rendered HTML after JS execution
            # This is what makes BrowserFetcher different from HttpFetcher —
            # this HTML includes content added by JavaScript
            html = await page.content()

            status = response.status if response else 200
            headers = response.headers if response else {}

            log.debug("BrowserFetcher OK: {} (HTTP {})", url, status)

            return FetchResult(
                url=url,
                status_code=status,
                html=html,
                headers=dict(headers),
                metadata={"browser": "chromium", "wait_until": wait_until},
            )

        except PlaywrightTimeout as e:
            log.warning("BrowserFetcher timeout: {} — {}", url, str(e))
            return self.make_error_result(url, e)

        except PlaywrightError as e:
            log.error("BrowserFetcher error: {} — {}", url, str(e))
            return self.make_error_result(url, e)

        except Exception as e:
            return self.make_error_result(url, e)

        finally:
            # Always close page and context — even if an exception occurred
            # This prevents browser memory leaks
            if page:
                await page.close()
            if context:
                await context.close()

    def fetch(self, url: str, **kwargs) -> FetchResult:
        """Sync wrapper for compatibility with BaseFetcher contract."""
        return asyncio.run(self.async_fetch(url, **kwargs))

    async def fetch_many(self, urls: list[str], **kwargs) -> list[FetchResult]:
        """
        Fetch multiple URLs using parallel browser tabs.
        The semaphore limits how many tabs are open simultaneously.
        Keep concurrency low (2-5) for browser fetching.
        """
        log.info(
            "BrowserFetcher: fetching {} URLs (max {} parallel tabs)",
            len(urls), self._concurrency
        )

        tasks = [self.async_fetch(url, **kwargs) for url in urls]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        results = []
        for url, result in zip(urls, raw_results):
            if isinstance(result, Exception):
                results.append(self.make_error_result(url, result))
            else:
                results.append(result)

        success_count = sum(1 for r in results if r.success)
        log.info("BrowserFetcher: {}/{} successful", success_count, len(urls))
        return results

    async def close(self) -> None:
        """
        Closes the browser and Playwright engine.
        Always call this when done — unclosed browsers waste significant RAM.
        """
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        log.debug("BrowserFetcher: browser closed")

    async def __aenter__(self):
        """Enables: async with BrowserFetcher() as fetcher: ..."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Automatically closes browser when exiting the with block."""
        await self.close()
        return False
