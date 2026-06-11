# ── anti_bot/headers_manager.py ───────────────────────────────────────────────
# HTTP headers manager — generates realistic browser-like headers.
#
# Why do headers matter for anti-bot evasion?
#   Modern anti-bot systems (Cloudflare, PerimeterX, DataDome) fingerprint
#   your requests by looking at the combination of headers — not just the
#   User-Agent, but also Accept-Language, Accept-Encoding, header ORDER,
#   and whether you're missing headers a real browser always sends.
#
#   A request with a realistic User-Agent but missing Sec-Fetch headers
#   is an obvious bot. This module builds complete, consistent header sets
#   that match what real Chrome/Firefox browsers actually send.

import random
from typing import Optional
from utils.logger import log

try:
    from fake_useragent import UserAgent
    FAKE_UA_AVAILABLE = True
except ImportError:
    FAKE_UA_AVAILABLE = False
    log.debug("fake-useragent not installed — using built-in UA list")


# ── Built-in User Agent pool ──────────────────────────────────────────────────
# Recent Chrome user agents across Windows, Mac, Linux
# Updated periodically — these are the most common in real traffic
CHROME_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
]

FIREFOX_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.2; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
]

ALL_USER_AGENTS = CHROME_USER_AGENTS + FIREFOX_USER_AGENTS


class HeadersManager:
    """
    Generates realistic, complete browser header sets for HTTP requests.

    Instead of just rotating User-Agents, this builds the FULL set of
    headers that a real browser sends — including Sec-Fetch headers,
    Accept headers, and Cache-Control. This is what separates basic
    scraping from professional anti-bot evasion.

    Usage:
        manager = HeadersManager(browser="chrome")

        # Get a complete header set for a navigation request
        headers = manager.get_headers(url="https://example.com/product")

        # Get just the User-Agent
        ua = manager.get_user_agent()
    """

    def __init__(
        self,
        browser: str = "chrome",       # "chrome", "firefox", or "random"
        use_fake_ua: bool = True,       # use fake-useragent library if available
        rotate_per_request: bool = True, # generate new UA each request
    ):
        """
        Args:
            browser:            preferred browser type for headers
            use_fake_ua:        use fake-useragent library for broader UA pool
            rotate_per_request: if True, different UA on each get_headers() call
                                if False, same UA throughout session
        """
        self.browser = browser
        self.use_fake_ua = use_fake_ua and FAKE_UA_AVAILABLE
        self.rotate_per_request = rotate_per_request

        # Session UA — used when rotate_per_request=False
        self._session_ua: Optional[str] = None

        if self.use_fake_ua:
            try:
                self._ua_generator = UserAgent(browsers=["chrome", "firefox"])
                log.debug("HeadersManager: using fake-useragent library")
            except Exception:
                self.use_fake_ua = False
                log.debug("HeadersManager: fake-useragent failed, using built-in pool")

        log.debug(
            "HeadersManager initialized (browser={}, rotate={})",
            browser, rotate_per_request
        )

    def get_user_agent(self) -> str:
        """
        Returns a random realistic User-Agent string.

        If fake-useragent is available, uses its larger, more diverse pool.
        Falls back to the built-in list otherwise.

        Returns:
            User-Agent string
        """
        if not self.rotate_per_request and self._session_ua:
            return self._session_ua

        if self.use_fake_ua:
            try:
                if self.browser == "chrome":
                    ua = self._ua_generator.chrome
                elif self.browser == "firefox":
                    ua = self._ua_generator.firefox
                else:
                    ua = self._ua_generator.random
            except Exception:
                ua = random.choice(ALL_USER_AGENTS)
        else:
            if self.browser == "chrome":
                ua = random.choice(CHROME_USER_AGENTS)
            elif self.browser == "firefox":
                ua = random.choice(FIREFOX_USER_AGENTS)
            else:
                ua = random.choice(ALL_USER_AGENTS)

        if not self.rotate_per_request:
            self._session_ua = ua

        return ua

    def get_headers(
        self,
        url: str = "",
        referer: str = "",
        extra: dict = None,
    ) -> dict:
        """
        Builds a complete, realistic browser header set.

        Generates the full set of headers Chrome or Firefox sends on a
        normal page navigation — not just User-Agent.

        The headers are ordered the same way real browsers send them,
        which some advanced fingerprinting systems check.

        Args:
            url:     the target URL — used to set Sec-Fetch-Site correctly
            referer: the referring page URL — set when navigating between pages
            extra:   additional headers to merge in

        Returns:
            dict of HTTP headers
        """
        ua = self.get_user_agent()
        is_chrome = "Chrome" in ua and "Firefox" not in ua

        if is_chrome:
            headers = self._chrome_headers(ua, url, referer)
        else:
            headers = self._firefox_headers(ua, url, referer)

        # Merge any extra headers — they take priority
        if extra:
            headers.update(extra)

        return headers

    def _chrome_headers(self, ua: str, url: str, referer: str) -> dict:
        """
        Builds the full header set that Chrome sends on page navigation.
        Header ORDER matters — some fingerprinting checks it.
        """
        headers = {
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": self._random_accept_language(),
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": self._sec_fetch_site(url, referer),
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
        }

        if referer:
            headers["Referer"] = referer

        return headers

    def _firefox_headers(self, ua: str, url: str, referer: str) -> dict:
        """
        Builds the full header set that Firefox sends on page navigation.
        Firefox sends slightly different headers than Chrome.
        """
        headers = {
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": self._random_accept_language(),
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": self._sec_fetch_site(url, referer),
            "Sec-Fetch-User": "?1",
        }

        if referer:
            headers["Referer"] = referer

        return headers

    def _sec_fetch_site(self, url: str, referer: str) -> str:
        """
        Calculates the correct Sec-Fetch-Site value.

        Sec-Fetch-Site tells the server where the request came from:
        - "none"        → direct navigation (typed URL or bookmark)
        - "same-origin" → link clicked on the same domain
        - "same-site"   → link clicked on same site but different subdomain
        - "cross-site"  → link clicked from a different domain
        """
        if not referer:
            return "none"

        try:
            from urllib.parse import urlparse
            url_domain = urlparse(url).netloc
            ref_domain = urlparse(referer).netloc

            if url_domain == ref_domain:
                return "same-origin"
            elif url_domain.split(".")[-2:] == ref_domain.split(".")[-2:]:
                return "same-site"
            else:
                return "cross-site"
        except Exception:
            return "none"

    def _random_accept_language(self) -> str:
        """
        Returns a realistic Accept-Language header value.
        Varies slightly to avoid identical fingerprints on every request.
        """
        languages = [
            "en-US,en;q=0.9",
            "en-GB,en;q=0.9",
            "en-US,en;q=0.9,es;q=0.8",
            "en-US,en;q=0.8",
            "en-US,en;q=0.9,fr;q=0.8",
        ]
        return random.choice(languages)

    def get_ajax_headers(self, referer: str = "", extra: dict = None) -> dict:
        """
        Returns headers appropriate for AJAX/XHR requests.
        Different from navigation headers — no Sec-Fetch-User,
        different Accept, and XMLHttpRequest marker.

        Used when scraping APIs or dynamic content loaded via JavaScript.
        """
        headers = {
            "User-Agent": self.get_user_agent(),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": self._random_accept_language(),
            "Accept-Encoding": "gzip, deflate, br",
            "X-Requested-With": "XMLHttpRequest",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "Connection": "keep-alive",
        }

        if referer:
            headers["Referer"] = referer

        if extra:
            headers.update(extra)

        return headers
