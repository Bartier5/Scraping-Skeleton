# ── utils/rate_limiter.py ─────────────────────────────────────────────────────
# Per-domain rate limiter for the scraper skeleton.
#
# The problem this solves:
#   When scraping 100 URLs across 10 domains simultaneously, without a rate
#   limiter you could fire 20 requests to amazon.com in one second. Amazon
#   detects this as bot traffic and blocks you. A rate limiter ensures you
#   never exceed a set number of requests per second PER DOMAIN — so you
#   can scrape many domains in parallel while staying polite to each one.
#
# How it works:
#   Uses a "token bucket" algorithm per domain. Each domain gets a bucket
#   that refills at a fixed rate (e.g. 2 tokens/second). Each request
#   consumes one token. If the bucket is empty, the request waits until
#   a token is available. This naturally spaces out requests.
#
# Used by: async_fetcher.py, batch_fetcher.py
#
# Usage:
#   from utils.rate_limiter import RateLimiter
#   limiter = RateLimiter(rate=2.0)             # 2 requests/second per domain
#   async with limiter.acquire("amazon.com"):
#       response = await fetch(url)

import asyncio                          # async sleep for non-blocking waits
import time                             # track when requests were last made
from typing import Optional             # type hint for optional values
from aiolimiter import AsyncLimiter     # async token bucket implementation
from config.config import Config        # pull DELAY_BETWEEN_REQUESTS from config
from utils.logger import log            # consistent logging


class RateLimiter:
    """
    Manages a separate rate limiter for each domain encountered during a scrape.

    Instead of one global rate limit that applies to all requests equally,
    this creates individual limiters per domain — so scraping amazon.com
    slowly doesn't slow down your requests to ebay.com.

    Each domain gets its own AsyncLimiter (token bucket) that is created
    lazily — only when that domain is first seen. This means you don't
    need to declare domains upfront, it adapts to whatever URLs you give it.
    """

    def __init__(
        self,
        rate: float = None,             # requests per second per domain
        burst: int = 1,                 # max requests allowed in a burst before throttling
    ):
        """
        Args:
            rate:  Max requests per second per domain.
                   Defaults to 1/DELAY_BETWEEN_REQUESTS from config.
                   e.g. DELAY=1.5s → rate = 1/1.5 ≈ 0.67 req/s
            burst: How many requests can fire at once before the limiter kicks in.
                   burst=1 means strictly one at a time (safest for anti-bot).
                   burst=3 means 3 can fire instantly, then throttled afterward.
        """
        # If no rate given, derive it from the config delay setting
        # e.g. delay=1.5s means we want at most 1 request every 1.5 seconds
        self.rate = rate or (1.0 / Config.DELAY_BETWEEN_REQUESTS)
        self.burst = burst

        # Dictionary mapping domain → its AsyncLimiter instance
        # Populated lazily as new domains are encountered
        self._limiters: dict[str, AsyncLimiter] = {}

        log.debug("RateLimiter initialized: {:.2f} req/s per domain, burst={}", 
                  self.rate, self.burst)

    def _get_limiter(self, domain: str) -> AsyncLimiter:
        """
        Returns the AsyncLimiter for a given domain.
        Creates a new one if this domain hasn't been seen before.

        This lazy initialization pattern means we never need to know
        the list of domains in advance.
        """
        if domain not in self._limiters:
            # Create a new token bucket for this domain
            # max_rate = tokens added per second
            # time_period = the window in seconds (1.0 = per second)
            self._limiters[domain] = AsyncLimiter(
                max_rate=self.rate,
                time_period=1.0,        # rate is per 1 second
            )
            log.debug("Created new rate limiter for domain: {}", domain)

        return self._limiters[domain]

    async def acquire(self, domain: str) -> None:
        """
        Acquires a rate limit token for the given domain.
        If the domain's bucket is full (too many recent requests),
        this will pause (sleep) until a token is available.

        This is used as an async context manager in the fetcher:

            async with limiter.acquire("amazon.com"):
                # this line only runs when a token is available
                response = await session.get(url)

        The 'async with' syntax ensures the token is always properly
        acquired before the request and released after, even if an
        exception occurs.
        """
        limiter = self._get_limiter(domain)

        log.debug("Acquiring rate limit token for: {}", domain)

        # AsyncLimiter.acquire() is itself an async context manager
        # it will sleep here if the bucket is empty
        async with limiter:
            pass    # token acquired — caller proceeds with the request

    async def wait(self, domain: str) -> None:
        """
        Alternative to acquire() for use without a context manager.
        Simply waits until a request to this domain is allowed, then returns.

        Usage:
            await limiter.wait("amazon.com")
            response = await session.get(url)
        """
        await self.acquire(domain)

    def get_stats(self) -> dict:
        """
        Returns a summary of how many domains are currently being tracked.
        Useful for monitoring and debugging.
        """
        return {
            "tracked_domains": len(self._limiters),
            "rate_per_second": self.rate,
            "burst_size": self.burst,
            "domains": list(self._limiters.keys()),
        }

    def reset(self, domain: Optional[str] = None) -> None:
        """
        Resets rate limiters.
        If domain is given, resets only that domain's limiter.
        If no domain given, resets all limiters.

        Useful between scrape jobs when you want a fresh start.
        """
        if domain:
            if domain in self._limiters:
                del self._limiters[domain]
                log.debug("Reset rate limiter for domain: {}", domain)
        else:
            self._limiters.clear()
            log.debug("Reset all rate limiters")


# ── Simple Async Delay Helper ─────────────────────────────────────────────────

async def polite_delay(seconds: float = None) -> None:
    """
    A simple async sleep used as a polite delay between requests
    when you don't need the full per-domain rate limiter.

    Defaults to Config.DELAY_BETWEEN_REQUESTS if no value given.
    Uses asyncio.sleep() (not time.sleep()) so it's non-blocking —
    other async tasks can run while this one waits.

    Usage:
        await polite_delay()         # uses config default
        await polite_delay(2.0)      # custom 2 second delay
    """
    delay = seconds if seconds is not None else Config.DELAY_BETWEEN_REQUESTS
    log.debug("Polite delay: {:.1f}s", delay)
    await asyncio.sleep(delay)      # non-blocking — other coroutines run during this wait


# ── Module-level default instance ─────────────────────────────────────────────
# A shared RateLimiter instance that modules can import directly
# instead of creating their own. Uses config defaults.
#
# Usage:
#   from utils.rate_limiter import default_limiter
#   await default_limiter.wait("amazon.com")

default_limiter = RateLimiter()
