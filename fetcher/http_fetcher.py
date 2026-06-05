# ── fetcher/http_fetcher.py ───────────────────────────────────────────────────
# Synchronous HTTP fetcher built on the `requests` library.
#
# When to use this fetcher:
#   - Simple scraping jobs where async isn't needed
#   - Small URL lists (under ~20 URLs)
#   - Situations where simplicity matters more than speed
#   - When the target site doesn't require JavaScript rendering
#
# When NOT to use this fetcher:
#   - Large batch jobs (use async_fetcher instead — much faster)
#   - JavaScript-heavy sites (use browser_fetcher instead)
#
# Inherits from BaseFetcher — implements all three required methods:
#   fetch()       → sync single URL
#   async_fetch() → wraps sync fetch in an async shell
#   fetch_many()  → sequential sync loop (use AsyncFetcher for concurrent)

import requests                         # sync HTTP library
from requests import Session            # Session reuses TCP connections for speed
from requests.exceptions import (
    RequestException,                   # base class for all requests errors
    Timeout,                            # request exceeded timeout limit
    ConnectionError as ReqConnectionError,  # network-level connection failure
    HTTPError,                          # 4xx/5xx response codes
)
import asyncio                          # needed to wrap sync calls as async
from typing import Optional

from fetcher.base_fetcher import BaseFetcher, FetchResult   # our contract
from config.config import Config        # central settings
from utils.logger import log
from utils.retry import retry           # exponential backoff decorator
from utils.helpers import get_domain   # extract domain for logging


class HttpFetcher(BaseFetcher):
    """
    Synchronous HTTP fetcher using the requests library.

    Creates a persistent Session on initialization — sessions reuse the
    underlying TCP connection across requests to the same host, which is
    faster than opening a new connection for every request.

    Default headers mimic a real Chrome browser so requests don't look
    like obvious bot traffic right out of the box.
    """

    # Default browser-like headers applied to every request
    # These make requests look like they came from a real Chrome browser
    DEFAULT_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",   # tell server we accept compressed responses
        "Connection": "keep-alive",                # reuse TCP connection
        "Upgrade-Insecure-Requests": "1",          # prefer HTTPS over HTTP
    }

    def __init__(self, config: dict = None, headers: dict = None):
        """
        Args:
            config:  optional overrides e.g. {"timeout": 60}
            headers: optional extra headers merged with DEFAULT_HEADERS
        """
        super().__init__(config)    # runs BaseFetcher.__init__ — stores self.config

        # Create a persistent session — reuses TCP connections across requests
        self.session = Session()

        # Merge default headers with any custom headers passed in
        # Custom headers take priority — they overwrite defaults with the same key
        merged_headers = {**self.DEFAULT_HEADERS, **(headers or {})}
        self.session.headers.update(merged_headers)

        log.debug("HttpFetcher session created with {} default headers",
                  len(self.session.headers))

    @retry()    # applies exponential backoff from utils/retry.py — uses Config.MAX_RETRIES
    def fetch(self, url: str, **kwargs) -> FetchResult:
        """
        Fetch a single URL synchronously using requests.

        The @retry() decorator wraps this method — if it raises an exception,
        it will automatically retry with exponential backoff before giving up.

        Args:
            url:     the URL to fetch
            **kwargs: optional per-request overrides:
                      - headers (dict): extra headers for this request only
                      - timeout (int): override Config.TIMEOUT for this request
                      - proxy (str):   proxy URL e.g. "http://user:pass@host:port"
                      - allow_redirects (bool): follow redirects (default True)

        Returns:
            FetchResult with html, status_code, headers, and error if failed
        """
        # Validate URL before making any network call
        if not self.validate_url(url):
            return self.make_error_result(url, ValueError(f"Invalid URL: {url}"))

        # Extract per-request overrides from kwargs, falling back to config defaults
        timeout = kwargs.get("timeout", Config.TIMEOUT)
        proxy_url = kwargs.get("proxy", None)
        extra_headers = kwargs.get("headers", {})
        allow_redirects = kwargs.get("allow_redirects", True)

        # Build proxies dict in the format requests expects
        # {"http": "http://proxy:port", "https": "http://proxy:port"}
        proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None

        log.debug("HttpFetcher fetching: {} (timeout={}s)", url, timeout)

        try:
            response = self.session.get(
                url,
                timeout=timeout,                    # seconds before giving up
                proxies=proxies,                    # None means no proxy
                headers=extra_headers,              # merged with session headers automatically
                allow_redirects=allow_redirects,    # follow 301/302 redirects
            )

            # raise_for_status() raises HTTPError for 4xx and 5xx status codes
            # This makes @retry() trigger on server errors automatically
            response.raise_for_status()

            log.debug("HttpFetcher OK: {} (HTTP {})", url, response.status_code)

            return FetchResult(
                url=url,
                status_code=response.status_code,
                html=response.text,                 # decoded HTML as string
                headers=dict(response.headers),     # convert CaseInsensitiveDict to plain dict
            )

        except Timeout as e:
            # Server didn't respond within timeout — retry will handle this
            log.warning("HttpFetcher timeout: {} after {}s", url, timeout)
            raise   # re-raise so @retry() catches it and retries

        except ReqConnectionError as e:
            # Network-level failure (DNS, refused connection, etc.)
            log.warning("HttpFetcher connection error: {}", url)
            raise   # re-raise for retry

        except HTTPError as e:
            # 4xx or 5xx response — log and return a failed FetchResult
            # Note: we DON'T re-raise here for 4xx (404 won't fix itself on retry)
            # but DO re-raise for 5xx (server errors may be temporary)
            status = e.response.status_code if e.response else 0
            if status >= 500:
                raise   # 5xx — worth retrying
            return self.make_error_result(url, e, status_code=status)

        except RequestException as e:
            # Catch-all for any other requests exception
            return self.make_error_result(url, e)

    async def async_fetch(self, url: str, **kwargs) -> FetchResult:
        """
        Async wrapper around the sync fetch() method.

        HttpFetcher is synchronous by design — this method allows it to be
        used in async contexts by running the sync call in a thread pool.
        asyncio.get_event_loop().run_in_executor() delegates the blocking
        call to a thread so the event loop isn't blocked.

        For high-concurrency async scraping, use AsyncFetcher instead —
        this is just a compatibility shim for when HttpFetcher is needed
        in an async context.
        """
        loop = asyncio.get_event_loop()

        # run_in_executor runs a blocking function in a thread pool
        # lambda wraps fetch() so kwargs can be passed through
        return await loop.run_in_executor(
            None,                               # None = default ThreadPoolExecutor
            lambda: self.fetch(url, **kwargs)   # the blocking function to run
        )

    async def fetch_many(self, urls: list[str], **kwargs) -> list[FetchResult]:
        """
        Fetch multiple URLs sequentially (sync loop).

        HttpFetcher doesn't do concurrent requests — for batch jobs use
        AsyncFetcher which runs requests simultaneously.

        This implementation is useful when you need sync behavior but
        still want a consistent fetch_many interface.
        """
        results = []
        total = len(urls)

        for i, url in enumerate(urls, 1):
            log.debug("HttpFetcher batch: {}/{} — {}", i, total, url)
            result = self.fetch(url, **kwargs)
            results.append(result)

        log.info("HttpFetcher batch complete: {}/{} successful",
                 sum(1 for r in results if r.success), total)
        return results

    def close(self) -> None:
        """
        Closes the requests Session and releases the underlying TCP connections.
        Call this when you're done scraping — good practice to avoid
        connection leaks, especially in long-running processes.

        Usage:
            fetcher = HttpFetcher()
            try:
                result = fetcher.fetch(url)
            finally:
                fetcher.close()

        Or use as a context manager (see __enter__/__exit__ below).
        """
        self.session.close()
        log.debug("HttpFetcher session closed")

    def __enter__(self):
        """Enables use as a context manager: with HttpFetcher() as f: ..."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Automatically closes session when exiting the with block."""
        self.close()
        return False    # False means exceptions are not suppressed
