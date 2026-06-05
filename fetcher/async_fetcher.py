# ── fetcher/async_fetcher.py ──────────────────────────────────────────────────
# Async HTTP fetcher built on aiohttp — the core of the batch engine.
#
# When to use this fetcher:
#   - Medium to large URL lists (20+ URLs)
#   - Any job where speed matters
#   - Multi-domain scraping where per-domain rate limiting is needed
#
# How async works here:
#   Instead of waiting for each request to finish before starting the next
#   (sequential), aiohttp fires multiple requests simultaneously and collects
#   results as they arrive. A semaphore caps how many run at once so we
#   don't overwhelm the server or trigger anti-bot systems.
#
#   Sequential (HttpFetcher):  req1 → wait → req2 → wait → req3 → wait
#   Concurrent (AsyncFetcher): req1 ─┐
#                              req2 ─┼─ all waiting simultaneously
#                              req3 ─┘
#
# Inherits from BaseFetcher — implements all three required methods.

import aiohttp                          # async HTTP client
import asyncio                          # event loop, semaphore, gather
from aiohttp import (
    ClientSession,                      # aiohttp's equivalent of requests.Session
    ClientTimeout,                      # configures connection + read timeouts
    ClientError,                        # base class for all aiohttp errors
    ClientResponseError,                # HTTP error responses (4xx/5xx)
    ClientConnectorError,               # connection-level failures
    ServerTimeoutError,                 # server took too long to respond
)
from typing import Optional

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
    - Each request gets retry logic via the shared retry helper
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
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    }

    def __init__(
        self,
        config: dict = None,
        headers: dict = None,
        concurrency: int = None,        # max simultaneous requests
        rate_limiter: RateLimiter = None,  # per-domain rate limiter
    ):
        """
        Args:
            config:       optional config overrides
            headers:      extra headers merged with DEFAULT_HEADERS
            concurrency:  max concurrent requests (defaults to Config.CONCURRENCY)
            rate_limiter: RateLimiter instance — defaults to module-level default
        """
        super().__init__(config)

        # Semaphore caps how many coroutines can be inside fetch at the same time
        # asyncio.Semaphore(10) means max 10 requests running simultaneously
        self._concurrency = concurrency or Config.CONCURRENCY
        self._semaphore = asyncio.Semaphore(self._concurrency)

        # Rate limiter for per-domain throttling
        self._rate_limiter = rate_limiter or default_limiter

        # Merge custom headers with defaults
        self._headers = {**self.DEFAULT_HEADERS, **(headers or {})}

        # Session starts as None — created lazily in _get_session()
        # because aiohttp sessions must be created inside async context
        self._session: Optional[ClientSession] = None

        log.debug("AsyncFetcher initialized (concurrency={})", self._concurrency)

    async def _get_session(self) -> ClientSession:
        """
        Returns the aiohttp ClientSession, creating it if it doesn't exist yet.

        Lazy initialization pattern — we can't create the session in __init__
        because __init__ is synchronous but ClientSession must be created
        inside a running event loop.

        The session is reused across all requests for connection pooling.
        """
        if self._session is None or self._session.closed:
            # ClientTimeout configures two separate timeout values:
            # total: max time for the entire request (connection + read)
            # connect: max time just to establish the TCP connection
            timeout = ClientTimeout(
                total=Config.TIMEOUT,
                connect=10,     # give up connecting after 10s even if total is longer
            )
            self._session = ClientSession(
                headers=self._headers,  # applied to every request from this session
                timeout=timeout,
            )
            log.debug("AsyncFetcher: new aiohttp session created")

        return self._session

    async def async_fetch(self, url: str, **kwargs) -> FetchResult:
        """
        Fetch a single URL asynchronously with concurrency limiting and rate limiting.

        The two layers of flow control:
        1. Semaphore — max N requests running at the same time across ALL domains
        2. Rate limiter — max M requests per second per DOMAIN

        Args:
            url:     the URL to fetch
            **kwargs: optional per-request overrides (headers, timeout, proxy)

        Returns:
            FetchResult with html, status_code, and error if failed
        """
        if not self.validate_url(url):
            return self.make_error_result(url, ValueError(f"Invalid URL: {url}"))

        domain = get_domain(url)
        extra_headers = kwargs.get("headers", {})
        proxy = kwargs.get("proxy", None)

        # ── Rate limiter: wait until this domain allows another request ───────
        # This is async — it yields control to the event loop while waiting
        # so other requests to different domains can proceed
        await self._rate_limiter.wait(domain)

        # ── Semaphore: wait until a concurrency slot is available ─────────────
        # "async with semaphore" decrements the counter on enter, increments on exit
        # When count reaches 0, any new coroutine waits here until a slot frees up
        async with self._semaphore:
            return await self._do_fetch(url, extra_headers, proxy)

    async def _do_fetch(
        self,
        url: str,
        extra_headers: dict = None,
        proxy: str = None,
    ) -> FetchResult:
        """
        Internal method that performs the actual aiohttp request.
        Separated from async_fetch() so retry logic is clean and contained.

        Handles all aiohttp-specific exceptions and maps them to FetchResult.
        """
        session = await self._get_session()
        attempts = 0
        max_attempts = Config.MAX_RETRIES

        while attempts < max_attempts:
            attempts += 1
            try:
                log.debug("AsyncFetcher attempt {}/{}: {}", attempts, max_attempts, url)

                # aiohttp uses async context manager for responses
                # "async with session.get()" ensures the response is properly closed
                async with session.get(
                    url,
                    headers=extra_headers or {},    # per-request extra headers
                    proxy=proxy,                    # None means no proxy
                    allow_redirects=True,           # follow redirects
                    ssl=False,                      # skip SSL verification (adjust for prod)
                ) as response:

                    # response.text() is a coroutine — must be awaited
                    # It reads the response body and decodes it to a string
                    html = await response.text(encoding="utf-8", errors="replace")

                    if response.status >= 500:
                        # 5xx server errors are worth retrying
                        log.warning("AsyncFetcher HTTP {}: {} (attempt {})",
                                    response.status, url, attempts)
                        if attempts < max_attempts:
                            # Exponential backoff: 1s, 2s, 4s between retries
                            await asyncio.sleep(2 ** (attempts - 1))
                            continue    # go back to the top of the while loop

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
                return self.make_error_result(url, TimeoutError(f"Timeout after {attempts} attempts"))

            except ClientConnectorError as e:
                # DNS failure, refused connection, etc.
                log.warning("AsyncFetcher connection error: {} — {}", url, str(e))
                if attempts < max_attempts:
                    await asyncio.sleep(2 ** (attempts - 1))
                    continue
                return self.make_error_result(url, e)

            except ClientResponseError as e:
                # HTTP error from raise_for_status() — 4xx or 5xx
                if e.status and e.status < 500:
                    # 4xx — don't retry (404 won't fix itself)
                    return self.make_error_result(url, e, status_code=e.status)
                # 5xx — retry
                if attempts < max_attempts:
                    await asyncio.sleep(2 ** (attempts - 1))
                    continue
                return self.make_error_result(url, e)

            except ClientError as e:
                # Catch-all for any other aiohttp client error
                return self.make_error_result(url, e)

        # Should not reach here but return error if somehow loop exits without return
        return self.make_error_result(url, RuntimeError("Max attempts exceeded"))

    def fetch(self, url: str, **kwargs) -> FetchResult:
        """
        Sync wrapper around async_fetch() for compatibility.
        Runs the async method in a new event loop.

        Use HttpFetcher if you need sync throughout — this is just
        a compatibility bridge so AsyncFetcher satisfies the BaseFetcher contract.
        """
        return asyncio.run(self.async_fetch(url, **kwargs))

    async def fetch_many(self, urls: list[str], **kwargs) -> list[FetchResult]:
        """
        Fetch multiple URLs concurrently.

        asyncio.gather() runs all coroutines simultaneously — the semaphore
        and rate limiter control how many actually execute at once.

        return_exceptions=True means a single failed request doesn't crash
        the entire batch — failures are returned as exception objects in
        the results list, then converted to FetchResult.

        Args:
            urls:    list of URLs to fetch concurrently
            **kwargs: overrides applied to every request in the batch

        Returns:
            list of FetchResult in the same order as the input URLs
        """
        log.info("AsyncFetcher: starting batch of {} URLs (concurrency={})",
                 len(urls), self._concurrency)

        # Create one coroutine per URL
        tasks = [self.async_fetch(url, **kwargs) for url in urls]

        # gather() runs all tasks concurrently and collects results
        # return_exceptions=True: exceptions are caught and returned as values
        # rather than propagating up and killing the whole gather
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert any exceptions that slipped through into proper FetchResults
        results = []
        for url, result in zip(urls, raw_results):
            if isinstance(result, Exception):
                # An exception escaped — wrap it in a FetchResult
                results.append(self.make_error_result(url, result))
            else:
                results.append(result)

        success_count = sum(1 for r in results if r.success)
        log.info("AsyncFetcher batch complete: {}/{} successful",
                 success_count, len(urls))

        return results

    async def close(self) -> None:
        """
        Closes the aiohttp session and releases all connections.
        Must be awaited — aiohttp session close is async.

        Always close the session when done to avoid ResourceWarning.
        """
        if self._session and not self._session.closed:
            await self._session.close()
            log.debug("AsyncFetcher session closed")

    async def __aenter__(self):
        """Enables use as async context manager: async with AsyncFetcher() as f: ..."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Automatically closes session when exiting the async with block."""
        await self.close()
        return False
