# ── examples/day2_example.py ─────────────────────────────────────────────────
# Day 2 mini example — wires url_utils and rate_limiter together
# to simulate a multi-domain batch crawl with per-domain throttling.
#
# No real HTTP requests are made — we simulate the fetch with asyncio.sleep()
# so you can see the rate limiter working without needing live URLs.
#
# Run with: python examples/day2_example.py

import sys
import os
import asyncio
import time

# Add project root to path so imports resolve correctly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.logger import log
from utils.helpers import ensure_dir
from utils.url_utils import (
    prepare_urls,
    chunk_urls,
    group_by_domain,
    build_paginated_urls,
    resolve_relative_urls,
)
from utils.rate_limiter import RateLimiter, polite_delay, default_limiter


# ── Simulated fetch function ──────────────────────────────────────────────────

async def simulate_fetch(url: str, limiter: RateLimiter) -> dict:
    """
    Simulates fetching a URL with rate limiting applied.
    In real usage (Day 4+) this will be replaced by the actual HTTP fetcher.

    Steps:
    1. Extract the domain from the URL
    2. Wait for a rate limit token for that domain
    3. Simulate the network request with a small sleep
    4. Return a fake result
    """
    from utils.helpers import get_domain

    domain = get_domain(url)

    # Wait until we're allowed to request this domain
    # If we've hit the rate limit, this will pause here automatically
    await limiter.wait(domain)

    # Simulate network latency (0.1s = 100ms fake request time)
    await asyncio.sleep(0.1)

    log.info("  Fetched: {}", url)
    return {"url": url, "status": 200, "domain": domain}


async def main():
    ensure_dir("logs")
    ensure_dir("data")

    log.info("=" * 60)
    log.info("Day 2 — URL Utils + Rate Limiter Demo")
    log.info("=" * 60)

    # ── 1. prepare_urls — full pipeline demo ─────────────────────────────────
    log.info("1. Testing prepare_urls() pipeline:")

    raw_urls = [
        "HTTPS://Books.ToScrape.COM/catalogue/page-1.html",   # uppercase — will normalize
        "https://books.toscrape.com/catalogue/page-1.html/",  # trailing slash — will normalize
        "https://books.toscrape.com/catalogue/page-1.html",   # duplicate after normalize
        "https://quotes.toscrape.com/page/1/",                # different domain, trailing slash
        "not-a-real-url",                                      # invalid — will be removed
        "",                                                    # empty — will be removed
        "ftp://files.example.com",                            # wrong scheme — will be removed
    ]

    log.info("  Raw URLs: {}", len(raw_urls))
    clean_urls = prepare_urls(raw_urls)
    log.info("  Clean URLs after pipeline: {}", len(clean_urls))
    for url in clean_urls:
        log.debug("  ✓ {}", url)

    # ── 2. build_paginated_urls ───────────────────────────────────────────────
    log.info("2. Building paginated URL lists:")

    product_pages = build_paginated_urls(
        "https://books.toscrape.com/catalogue",
        total_pages=5,
        page_param="page",
        start_page=1,
    )
    log.info("  Generated {} paginated URLs:", len(product_pages))
    for url in product_pages:
        log.debug("  {}", url)

    # ── 3. resolve_relative_urls ──────────────────────────────────────────────
    log.info("3. Resolving relative URLs:")

    base = "https://books.toscrape.com"
    relative_links = [
        "/catalogue/page-2.html",
        "/catalogue/category/books/mystery_3/",
        "https://quotes.toscrape.com/page/2/",   # already absolute — unchanged
    ]
    resolved = resolve_relative_urls(base, relative_links)
    for original, resolved_url in zip(relative_links, resolved):
        log.info("  {} → {}", original, resolved_url)

    # ── 4. chunk_urls ─────────────────────────────────────────────────────────
    log.info("4. Chunking 20 URLs into batches of 5:")

    # Generate 20 fake URLs across 4 domains
    batch_urls = (
        [f"https://amazon.com/product/{i}" for i in range(1, 6)] +
        [f"https://ebay.com/item/{i}" for i in range(1, 6)] +
        [f"https://walmart.com/item/{i}" for i in range(1, 6)] +
        [f"https://target.com/product/{i}" for i in range(1, 6)]
    )

    chunks = list(chunk_urls(batch_urls, chunk_size=5))
    log.info("  {} URLs split into {} chunks of 5:", len(batch_urls), len(chunks))
    for i, chunk in enumerate(chunks, 1):
        log.debug("  Chunk {}: {} URLs | first={} last={}",
                  i, len(chunk), chunk[0].split("/")[-1], chunk[-1].split("/")[-1])

    # ── 5. group_by_domain ────────────────────────────────────────────────────
    log.info("5. Grouping URLs by domain:")

    grouped = group_by_domain(batch_urls)
    for domain, urls in grouped.items():
        log.info("  {} → {} URLs", domain, len(urls))

    # ── 6. Rate limiter — the main event ──────────────────────────────────────
    log.info("6. Rate limiter simulation — 12 URLs across 3 domains:")
    log.info("   Rate: 2 requests/second per domain")
    log.info("   Watch how requests to the same domain are spaced out...")

    # Create a limiter allowing 2 requests per second per domain
    # This means between requests to the same domain there's ~0.5s gap
    limiter = RateLimiter(rate=2.0, burst=1)

    # 12 URLs — 4 per domain, interleaved so same-domain requests are spread out
    simulation_urls = []
    for i in range(1, 5):
        simulation_urls.append(f"https://siteA.com/page-{i}")
        simulation_urls.append(f"https://siteB.com/page-{i}")
        simulation_urls.append(f"https://siteC.com/page-{i}")

    start_time = time.time()

    # Fire all 12 requests concurrently using asyncio.gather()
    # gather() runs all coroutines at the same time — the rate limiter
    # controls how fast each domain's requests actually execute
    tasks = [simulate_fetch(url, limiter) for url in simulation_urls]
    results = await asyncio.gather(*tasks)

    total_time = time.time() - start_time

    log.info("Simulation complete:")
    log.info("  Total URLs processed: {}", len(results))
    log.info("  Total time: {:.2f}s", total_time)
    log.info("  Successful fetches: {}", sum(1 for r in results if r["status"] == 200))

    # Show rate limiter stats
    stats = limiter.get_stats()
    log.info("  Domains tracked by limiter: {}", stats["tracked_domains"])
    log.info("  Tracked domains: {}", stats["domains"])

    # ── 7. polite_delay demo ──────────────────────────────────────────────────
    log.info("7. Polite delay demo:")
    log.info("  Waiting 0.3s between operations...")
    await polite_delay(0.3)
    log.info("  Done waiting — continuing")

    log.info("=" * 60)
    log.success("Day 2 complete — url_utils and rate_limiter working correctly")
    log.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())   # asyncio.run() is the entry point for async programs
