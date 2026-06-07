# ── fetcher/batch_fetcher.py ──────────────────────────────────────────────────
# Batch fetcher — designed specifically for large URL lists (50-1000+ URLs).
#
# What makes this different from AsyncFetcher?
#   AsyncFetcher fires ALL URLs at once with a semaphore cap.
#   BatchFetcher processes URLs in CHUNKS — it completes one chunk fully
#   before starting the next. This gives you:
#   - Predictable memory usage (only one chunk in flight at a time)
#   - Progress tracking per chunk (useful for long-running jobs)
#   - Natural checkpoint points between chunks (easier to resume)
#   - Better politeness — server gets breathing room between chunks
#
# When to use BatchFetcher vs AsyncFetcher:
#   AsyncFetcher  → under 50 URLs, want maximum speed
#   BatchFetcher  → 50+ URLs, want progress visibility and resumability
#
# Inherits from BaseFetcher — wraps AsyncFetcher internally.

import asyncio
from typing import Callable, Optional

from fetcher.base_fetcher import BaseFetcher, FetchResult
from fetcher.async_fetcher import AsyncFetcher
from utils.url_utils import chunk_urls, prepare_urls
from utils.rate_limiter import RateLimiter
from config.config import Config
from utils.logger import log


class BatchFetcher(BaseFetcher):
    """
    Chunk-based batch fetcher for large URL lists.

    Internally uses AsyncFetcher for each chunk — so all the concurrency,
    rate limiting, retry, and DNS fixes are already baked in.

    The key addition is chunk-level orchestration:
    - Splits URL list into chunks of configurable size
    - Processes one chunk at a time with asyncio.gather()
    - Reports progress after each chunk completes
    - Supports an optional callback for per-result processing
    - Supports filtering already-seen URLs before fetching
    """

    def __init__(
        self,
        config: dict = None,
        headers: dict = None,
        concurrency: int = None,        # concurrent requests per chunk
        chunk_size: int = None,         # how many URLs per chunk
        rate_limiter: RateLimiter = None,
    ):
        """
        Args:
            config:       optional config overrides
            headers:      extra headers merged with defaults
            concurrency:  max concurrent requests within a chunk
            chunk_size:   how many URLs to process per chunk
                          defaults to Config.CONCURRENCY * 2
            rate_limiter: per-domain rate limiter
        """
        super().__init__(config)

        self._concurrency = concurrency or Config.CONCURRENCY
        # chunk_size defaults to 2x concurrency — keeps pipeline full
        # without building up too much backpressure
        self._chunk_size = chunk_size or (self._concurrency * 2)
        self._rate_limiter = rate_limiter

        # Internal AsyncFetcher that handles the actual HTTP work
        # BatchFetcher is a coordinator — AsyncFetcher is the worker
        self._async_fetcher = AsyncFetcher(
            config=config,
            headers=headers,
            concurrency=self._concurrency,
            rate_limiter=rate_limiter,
        )

        log.debug(
            "BatchFetcher initialized (concurrency={}, chunk_size={})",
            self._concurrency, self._chunk_size
        )

    async def fetch_batch(
        self,
        urls: list[str],
        on_result: Optional[Callable[[FetchResult], None]] = None,
        skip_urls: Optional[set[str]] = None,
        prepare: bool = True,
    ) -> list[FetchResult]:
        """
        Fetch a large list of URLs in chunks with progress reporting.

        Args:
            urls:       list of URLs to fetch
            on_result:  optional callback called after each successful fetch
                        e.g. lambda result: storage.save([parse(result.html)])
                        This lets you process results as they arrive rather
                        than waiting for the entire batch to complete
            skip_urls:  set of URLs to skip (already scraped in a previous run)
                        This is how delta scraping works at the fetcher level
            prepare:    if True, runs urls through prepare_urls() first
                        (normalize, validate, deduplicate)

        Returns:
            list of all FetchResults in input order
        """
        # Step 1 — optionally run through url preparation pipeline
        if prepare:
            urls = prepare_urls(urls)

        # Step 2 — filter out already-seen URLs (delta scraping)
        if skip_urls:
            original_count = len(urls)
            urls = [u for u in urls if u not in skip_urls]
            skipped = original_count - len(urls)
            if skipped > 0:
                log.info("BatchFetcher: skipped {} already-seen URLs", skipped)

        if not urls:
            log.info("BatchFetcher: no URLs to fetch after filtering")
            return []

        total_urls = len(urls)
        total_chunks = (total_urls + self._chunk_size - 1) // self._chunk_size
        all_results: list[FetchResult] = []

        log.info(
            "BatchFetcher: {} URLs → {} chunks of {} (concurrency={})",
            total_urls, total_chunks, self._chunk_size, self._concurrency
        )

        # Step 3 — process each chunk sequentially
        for chunk_num, chunk in enumerate(
            chunk_urls(urls, self._chunk_size), start=1
        ):
            log.info(
                "BatchFetcher: chunk {}/{} — {} URLs",
                chunk_num, total_chunks, len(chunk)
            )

            # Fetch all URLs in this chunk concurrently
            # AsyncFetcher.fetch_many() handles semaphore + rate limiting
            chunk_results = await self._async_fetcher.fetch_many(chunk)

            # Process results — call callback if provided
            for result in chunk_results:
                if result.success and on_result:
                    # Call the callback with each successful result
                    # This allows pipeline integration without waiting
                    # for the whole batch to finish
                    try:
                        on_result(result)
                    except Exception as e:
                        # Callback errors should never kill the batch
                        log.error("BatchFetcher: on_result callback error: {}", str(e))

            all_results.extend(chunk_results)

            # Progress report after each chunk
            success_so_far = sum(1 for r in all_results if r.success)
            log.info(
                "BatchFetcher: progress {}/{} URLs complete ({} successful)",
                len(all_results), total_urls, success_so_far
            )

        success_count = sum(1 for r in all_results if r.success)
        fail_count = len(all_results) - success_count
        log.info(
            "BatchFetcher: complete — {} successful, {} failed out of {}",
            success_count, fail_count, total_urls
        )

        return all_results

    def fetch(self, url: str, **kwargs) -> FetchResult:
        """Single URL sync fetch — delegates to AsyncFetcher."""
        return self._async_fetcher.fetch(url, **kwargs)

    async def async_fetch(self, url: str, **kwargs) -> FetchResult:
        """Single URL async fetch — delegates to AsyncFetcher."""
        return await self._async_fetcher.async_fetch(url, **kwargs)

    async def fetch_many(self, urls: list[str], **kwargs) -> list[FetchResult]:
        """
        Implements BaseFetcher.fetch_many() using chunk-based processing.
        For full batch features (callbacks, skip_urls) use fetch_batch() directly.
        """
        return await self.fetch_batch(urls)

    async def close(self) -> None:
        """Closes the internal AsyncFetcher session."""
        await self._async_fetcher.close()
        log.debug("BatchFetcher closed")

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
        return False
