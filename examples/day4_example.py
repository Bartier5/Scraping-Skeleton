# ── examples/day4_example.py ──────────────────────────────────────────────────
# Day 4 mini example — real HTTP requests using HttpFetcher and AsyncFetcher.
# We scrape books.toscrape.com and quotes.toscrape.com — both are free,
# publicly available scraping practice sites that welcome scrapers.
#
# Run with: python examples/day4_example.py

import sys
import os
import asyncio
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sys
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from utils.logger import log
from utils.helpers import ensure_dir, timestamp
from utils.url_utils import build_paginated_urls, prepare_urls
from fetcher.http_fetcher import HttpFetcher
from fetcher.async_fetcher import AsyncFetcher


async def main():
    ensure_dir("logs")
    ensure_dir("data")

    log.info("=" * 60)
    log.info("Day 4 — HttpFetcher + AsyncFetcher Live Demo")
    log.info("=" * 60)

    # ── 1. HttpFetcher — single sync request ──────────────────────────────────
    log.info("1. HttpFetcher — single sync fetch:")

    with HttpFetcher() as fetcher:
        result = fetcher.fetch("https://books.toscrape.com")

        log.info("  URL:         {}", result.url)
        log.info("  Status:      {}", result.status_code)
        log.info("  Success:     {}", result.success)
        log.info("  HTML length: {} chars", len(result.html))
        log.info("  First 80 chars: {!r}", result.html[:80].strip())

    # ── 2. HttpFetcher — context manager + validate ───────────────────────────
    log.info("2. HttpFetcher — invalid URL handling:")

    with HttpFetcher() as fetcher:
        bad_result = fetcher.fetch("not-a-real-url")
        log.info("  Invalid URL result: success={} error={}",
                 bad_result.success, bad_result.error)

    # ── 3. AsyncFetcher — single async fetch ──────────────────────────────────
    log.info("3. AsyncFetcher — single async fetch:")

    async with AsyncFetcher() as fetcher:
        result = await fetcher.async_fetch("https://quotes.toscrape.com")
        log.info("  URL:         {}", result.url)
        log.info("  Status:      {}", result.status_code)
        log.info("  Success:     {}", result.success)
        log.info("  HTML length: {} chars", len(result.html))

    # ── 4. AsyncFetcher — batch fetch (the real power) ────────────────────────
    log.info("4. AsyncFetcher — batch fetch across two domains:")

    # Build URLs from two different practice sites
    book_pages = build_paginated_urls(
        "https://books.toscrape.com/catalogue/page",
        total_pages=3,
        page_param=None,   # this site uses path-based pagination: /page-1.html
    )

    # books.toscrape.com uses path-based pagination, not query params
    # so we build them manually
    book_urls = [
        "https://books.toscrape.com/catalogue/page-1.html",
        "https://books.toscrape.com/catalogue/page-2.html",
        "https://books.toscrape.com/catalogue/page-3.html",
    ]
    quote_urls = [
        "https://quotes.toscrape.com/page/1/",
        "https://quotes.toscrape.com/page/2/",
        "https://quotes.toscrape.com/page/3/",
    ]

    all_urls = book_urls + quote_urls
    clean_urls = prepare_urls(all_urls)

    log.info("  Fetching {} URLs concurrently...", len(clean_urls))
    start = time.time()

    async with AsyncFetcher(concurrency=6) as fetcher:
        results = await fetcher.fetch_many(clean_urls)

    elapsed = time.time() - start

    # Summarize results
    successes = [r for r in results if r.success]
    failures = [r for r in results if r.failed]

    log.info("  Batch complete in {:.2f}s:", elapsed)
    log.info("  ✓ Successful: {}/{}", len(successes), len(results))
    log.info("  ✗ Failed:     {}/{}", len(failures), len(results))

    for result in results:
        status_icon = "✓" if result.success else "✗"
        log.info("  {} {} | HTTP {} | {} chars",
                 status_icon,
                 result.url,
                 result.status_code,
                 len(result.html))

    # ── 5. Speed comparison: sequential vs concurrent ─────────────────────────
    log.info("5. Speed comparison — sequential vs concurrent (3 URLs):")

    test_urls = [
        "https://books.toscrape.com/catalogue/page-1.html",
        "https://quotes.toscrape.com/page/1/",
        "https://books.toscrape.com/catalogue/page-2.html",
    ]

    # Sequential (HttpFetcher)
    seq_start = time.time()
    with HttpFetcher() as sync_fetcher:
        sync_results = await sync_fetcher.fetch_many(test_urls)
    seq_elapsed = time.time() - seq_start

    # Concurrent (AsyncFetcher)
    async with AsyncFetcher(concurrency=3) as async_fetcher:
        conc_start = time.time()
        async_results = await async_fetcher.fetch_many(test_urls)
        conc_elapsed = time.time() - conc_start

    log.info("  Sequential (HttpFetcher): {:.2f}s", seq_elapsed)
    log.info("  Concurrent (AsyncFetcher): {:.2f}s", conc_elapsed)
    if conc_elapsed > 0:
        speedup = seq_elapsed / conc_elapsed
        log.info("  Speedup: {:.1f}x faster with AsyncFetcher", speedup)

    log.info("=" * 60)
    log.success("Day 4 complete — real HTTP fetching working with retry + concurrency")
    log.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
