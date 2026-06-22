# ── spiders/login_spider.py ───────────────────────────────────────────────────
# Test 2B — Login wall spider.
# Target: quotes.toscrape.com/login
#
# Pattern: form-based login, session cookies reused across all requests.
# After login, scrapes pages only accessible to authenticated users.
#
# Two approaches shown:
#   Approach A — SessionManager (for standard HTML forms, no JS)
#   Approach B — Playwright (for JS-heavy or complex login flows)
#
# quotes.toscrape.com uses a standard HTML form, so Approach A works here.
# For sites like LinkedIn or Google, you'd need Approach B.

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


class LoginSpider(BaseSpider):
    """
    Scrapes content behind a login wall.

    Uses SessionManager to:
    1. POST login credentials to the login form
    2. Store the session cookies
    3. Reuse those cookies on every subsequent request
    4. Auto-detect session expiry and re-login if needed

    The key difference from other spiders:
    Every fetch goes through an authenticated session instead of a
    fresh connection. The site sees all requests as coming from the
    same logged-in user.
    """

    LOGIN_URL  = "https://quotes.toscrape.com/login"
    TARGET_URL = "https://quotes.toscrape.com/"

    SCRAPE_URLS = [
        "https://quotes.toscrape.com/",
        "https://quotes.toscrape.com/page/2/",
        "https://quotes.toscrape.com/page/3/",
    ]

    def __init__(
        self,
        username: str = "user",
        password: str = "password",
        **kwargs,
    ):
        super().__init__(name="LoginSpider", **kwargs)
        self.username = username
        self.password = password

        self._cleaner     = DataCleaner()
        self._transformer = DataTransformer(add_metadata=True)
        self._validator   = DataValidator(schema=QuoteSchema, strict=False)

        log.debug("LoginSpider: initialized for {}", self.LOGIN_URL)

    async def run(self, urls: list[str] = None, **kwargs) -> dict:
        urls = prepare_urls(urls or self.SCRAPE_URLS)
        self.start_run(urls)

        session = await self._login()
        if not session:
            log.error("LoginSpider: login failed — cannot proceed")
            self.finish_run()
            return self.get_stats()

        # No context manager — just call directly
        for url in urls:
            await self._scrape_page(url, session)

        self.finish_run()
        return self.get_stats()

    async def _login(self):
        from fetcher.session_manager import SessionManager, SessionConfig

        log.info("LoginSpider: logging in as '{}'...", self.username)

        config = SessionConfig(
            login_url=self.LOGIN_URL,
            credentials={
                "username": self.username,
                "password": self.password,
            },
            success_check="Logout",
            expiry_signals=["/login", "sign-in"],
            session_ttl=3600,
        )

        session = SessionManager(session_config=config)

        # login() is sync not async — no await
        result = session.login()

        if result:
            log.info("LoginSpider: login successful — session active")
            return session
        else:
            log.error("LoginSpider: login failed")
            return None

    async def _scrape_page(self, url: str, session) -> int:
        log.info("LoginSpider: scraping (authenticated) {}", url)

        # Use async_fetch — it wraps the sync fetch in a thread pool
        # The sync fetch carries the session cookies automatically
        result = await session.async_fetch(url)

        if result.failed:
            log.warning("LoginSpider: fetch failed for {}", url)
            return 0

        soup = self.parser.make_soup(result.html)

        # Check we're logged in — look for the logout link
        is_logged_in = bool(soup.select("a[href='/logout']"))
        log.info("LoginSpider: authenticated = {}", is_logged_in)

        texts      = self.parser.get_all_text(soup, "span.text")
        authors    = self.parser.get_all_text(soup, "small.author")
        tag_groups = []
        for quote_el in soup.select("div.quote"):
            tags = [t.get_text(strip=True) for t in quote_el.select("a.tag")]
            tag_groups.append(tags)

        if not texts:
            log.warning("LoginSpider: no quotes found on {}", url)
            return 0

        raw_items = [
            {
                "text":   text,
                "author": author,
                "tags":   tag_groups[i] if i < len(tag_groups) else [],
                "url":    url,
            }
            for i, (text, author) in enumerate(zip(texts, authors))
        ]

        self._stats["items_scraped"] += len(raw_items)
        cleaned     = self._cleaner.clean_items(raw_items)
        transformed = self._transformer.transform_items(cleaned)
        batch       = self._validator.validate_batch(transformed)
        saved       = await self.save(batch.valid_items)

        log.info("LoginSpider: {} quotes saved from {}", saved, url)
        return saved