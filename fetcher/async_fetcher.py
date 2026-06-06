# ── fetcher/async_fetcher.py ──────────────────────────────────────────────────
# Async HTTP fetcher built on aiohttp — the core of the batch engine.
#
# When to use this fetcher:
#   - Medium to large URL lists (20+ URLs)
#   - Any job where speed matters
#   - Multi-domain scraping where per-domain rate limiting is needed
#
# Inherits from BaseFetcher — implements all three required methods.

import sys
import ssl
import asyncio
import aiohttp
from aiohttp import (
    ClientSession,
    ClientTimeout,
    ClientError,
    ClientResponseError,
    ClientConnectorError,
    ServerTimeoutError,
)
from typing import Optional

# Windows fix — aiohttp DNS resolution fails on ProactorEventLoop.
# SelectorEventLoop handles DNS correctly with aiohttp on Windows.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fetcher.base_fetcher import BaseFetcher, FetchResult
from config.config import Config
from utils.logger import log
from utils.helpers import get_domain
from utils.rate_limiter import RateLimiter, default_limiter


class AsyncFetcher(BaseFetcher):
    """
    Async HTTP fetcher using aiohttp with semaphore-controlled concurrency.

    Key design decisions:
    - Session is created lazily (on first use) because aiohttp sessions
      must be created inside an async context
    - Semaphore limits concurrent requests globally
    - Rate limiter controls per-domain request rate
    - Each request gets retry logic via exponential backoff
    """

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
        "Accept-Encoding": "gzip, deflate",   # no br — avoids Brotli decode errors
        "Connection": "keep-alive",
    }

    def __init__(
        self,
        config: dict = None,
        headers: dict = None,
        concurrency: int = None,
        rate_limiter: RateLimiter = None,
    ):
        super().__init__(config)

        # Semaphore caps how many coroutines run simultaneously
        self._concurrency = concurrency or Config.CONCURRENCY
        self._semaphore = asyncio.Semaphore(self._concurrency)

        # Per-domain rate limiter
        self._rate_limiter = rate_limiter or default_limiter

        # Merge custom headers with defaults
        self._headers = {**self.DEFAULT_HEADERS, **(headers or {})}

        # Session is None until first request — lazy initialization
        self._session: Optional[ClientSession] = None

        log.debug("AsyncFetcher initialized (concurrency={})", self._concurrency)

    async def _get_session(self) -> ClientSession:
        """
        Returns the aiohttp ClientSession, creating it if it doesn't exist yet.
        Lazy initialization — ClientSession must be created inside async context.

        Uses TCPConnector with use_dns_cache=False to fix Windows DNS issues
        where aiohttp cannot contact DNS servers through ProactorEventLoop.
        """
        if self._session is None or self._session.closed:

            # SSL context — disables certificate verification for scraping
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE

            # AsyncResolver routes DNS through Google's servers directly,
# completely bypassing the Windows DNS stack which breaks aiohttp.
            import aiodns
            resolver = aiohttp.AsyncResolver(nameservers=["8.8.8.8", "8.8.4.4"])

            connector = aiohttp.TCPConnector(
            resolver=resolver,      # use Google DNS instead of Windows system DNS
            ssl=ssl_ctx,            # apply SSL context at connector level
            use_dns_cache=False,    # don't cache DNS results
            ttl_dns_cache=0,
)

            # ClientTimeout sets max time for full request and connection phase
            session_timeout = ClientTimeout(
                total=Config.TIMEOUT,
                connect=10,
            )

            self._session = ClientSession(
                headers=self._headers,
                timeout=session_timeout,
                connector=connector,
            )

            log.debug("AsyncFetcher: new aiohttp session created")

        return self._session

    async def async_fetch(self, url: str, **kwargs) -> FetchResult:
        """
        Fetch a single URL asynchronously with concurrency and rate limiting.

        Two layers of flow control:
        1. Rate limiter — max N requests per second per DOMAIN
        2. Semaphore — max M requests running simultaneously across ALL domains

        Args:
            url:      the URL to fetch
            **kwargs: optional overrides — headers, proxy

        Returns:
            FetchResult with html, status_code, and error if failed
        """
        if not self.validate_url(url):
            return self.make_error_result(url, ValueError(f"Invalid URL: {url}"))

        domain = get_domain(url)
        extra_headers = kwargs.get("headers", {})
        proxy = kwargs.get("proxy", None)

        # Wait for rate limit token for this domain
        await self._rate_limiter.wait(domain)

        # Wait for a concurrency slot then fetch
        async with self._semaphore:
            return await self._do_fetch(url, extra_headers, proxy)

    async def _do_fetch(
        self,
        url: str,
        extra_headers: dict = None,
        proxy: str = None,
    ) -> FetchResult:
        """
        Internal method that performs the actual aiohttp request with retry.
        Exponential backoff between attempts: 1s, 2s, 4s.
        """
        session = await self._get_session()
        attempts = 0
        max_attempts = Config.MAX_RETRIES

        while attempts < max_attempts:
            attempts += 1
            try:
                log.debug("AsyncFetcher attempt {}/{}: {}", attempts, max_attempts, url)

                async with session.get(
                    url,
                    headers=extra_headers or {},
                    proxy=proxy,
                    allow_redirects=True,
                ) as response:

                    # response.text() reads and decodes the body
                    html = await response.text(encoding="utf-8", errors="replace")

                    if response.status >= 500:
                        # 5xx — worth retrying, server may recover
                        log.warning("AsyncFetcher HTTP {}: {} (attempt {})",
                                    response.status, url, attempts)
                        if attempts < max_attempts:
                            await asyncio.sleep(2 ** (attempts - 1))
                            continue

                    log.debug("AsyncFetcher OK: {} (HTTP {})", url, response.status)
                    return FetchResult(
                        url=url,
                        status_code=response.status,
                        html=html,
                        headers=dict(response.headers),
                    )

            except ServerTimeoutError:
                log.warning("AsyncFetcher timeout: {} (attempt {})", url, attempts)
                if attempts < max_attempts:
                    await asyncio.sleep(2 ** (attempts - 1))
                    continue
                return self.make_error_result(
                    url, TimeoutError(f"Timeout after {attempts} attempts")
                )

            except ClientConnectorError as e:
                # DNS failure, refused connection, network error
                log.warning("AsyncFetcher connection error: {} — {}", url, str(e))
                if attempts < max_attempts:
                    await asyncio.sleep(2 ** (attempts - 1))
                    continue
                return self.make_error_result(url, e)

            except ClientResponseError as e:
                if e.status and e.status < 500:
                    # 4xx — don't retry, won't fix itself
                    return self.make_error_result(url, e, status_code=e.status)
                if attempts < max_attempts:
                    await asyncio.sleep(2 ** (attempts - 1))
                    continue
                return self.make_error_result(url, e)

            except ClientError as e:
                # Catch-all for any other aiohttp error
                return self.make_error_result(url, e)

        return self.make_error_result(url, RuntimeError("Max attempts exceeded"))

    def fetch(self, url: str, **kwargs) -> FetchResult:
        """
        Sync wrapper around async_fetch() for BaseFetcher compatibility.
        Use HttpFetcher if you need sync throughout.
        """
        return asyncio.run(self.async_fetch(url, **kwargs))

    async def fetch_many(self, urls: list[str], **kwargs) -> list[FetchResult]:
        """
        Fetch multiple URLs concurrently using asyncio.gather().
        Semaphore and rate limiter control actual execution rate.
        return_exceptions=True ensures one failure never kills the batch.

        Args:
            urls:     list of URLs to fetch
            **kwargs: overrides applied to every request

        Returns:
            list of FetchResult in same order as input URLs
        """
        log.info("AsyncFetcher: starting batch of {} URLs (concurrency={})",
                 len(urls), self._concurrency)

        # One coroutine per URL — gather runs them all concurrently
        tasks = [self.async_fetch(url, **kwargs) for url in urls]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Wrap any escaped exceptions into proper FetchResults
        results = []
        for url, result in zip(urls, raw_results):
            if isinstance(result, Exception):
                results.append(self.make_error_result(url, result))
            else:
                results.append(result)

        success_count = sum(1 for r in results if r.success)
        log.info("AsyncFetcher batch complete: {}/{} successful",
                 success_count, len(urls))

        return results

    async def close(self) -> None:
        """Closes the aiohttp session and releases all connections."""
        if self._session and not self._session.closed:
            await self._session.close()
            log.debug("AsyncFetcher session closed")

    async def __aenter__(self):
        """Enables: async with AsyncFetcher() as fetcher: ..."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Automatically closes session on exit."""
        await self.close()
        return False