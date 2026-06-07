# ── examples/day5_example.py ──────────────────────────────────────────────────
# Day 5 mini example — BatchFetcher, BrowserFetcher, SessionManager demo.
#
# BrowserFetcher requires Playwright — install with:
#   pip install playwright && playwright install chromium
#
# Run with: python examples/day5_example.py

import sys
import os
import asyncio
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from utils.logger import log
from utils.helpers import ensure_dir
from fetcher.batch_fetcher import BatchFetcher
from fetcher.browser_fetcher import BrowserFetcher
from fetcher.session_manager import SessionManager, SessionConfig


async def main():
    ensure_dir("logs")
    ensure_dir("data")

    log.info("=" * 60)
    log.info("Day 5 — BatchFetcher + BrowserFetcher + SessionManager")
    log.info("=" * 60)

    # ── 1. BatchFetcher — 20 URLs in chunks ──────────────────────────────────
    log.info("1. BatchFetcher — 20 URLs across 2 domains in chunks of 6:")

    urls = (
        [f"https://books.toscrape.com/catalogue/page-{i}.html"
         for i in range(1, 11)] +
        [f"https://quotes.toscrape.com/page/{i}/"
         for i in range(1, 11)]
    )

    # Track results as they arrive via callback
    results_log = []

    def on_result(result):
        """Called immediately after each successful fetch — no waiting."""
        results_log.append(result.url)
        log.debug("  → Processed: {} ({} chars)", result.url, len(result.html))

    start = time.time()
    async with BatchFetcher(concurrency=5, chunk_size=6) as fetcher:
        results = await fetcher.fetch_batch(
            urls,
            on_result=on_result,    # process results as they arrive
            prepare=True,           # normalize + validate + dedup first
        )
    elapsed = time.time() - start

    success = [r for r in results if r.success]
    failed = [r for r in results if r.failed]

    log.info("  Total time: {:.2f}s", elapsed)
    log.info("  Successful: {}/{}", len(success), len(results))
    log.info("  Failed:     {}/{}", len(failed), len(results))
    log.info("  Callback fired {} times", len(results_log))

    # ── 2. BatchFetcher — delta scraping with skip_urls ───────────────────────
    log.info("2. BatchFetcher — delta scraping (skip already-seen URLs):")

    all_urls = [f"https://books.toscrape.com/catalogue/page-{i}.html"
                for i in range(1, 6)]

    # Simulate already having scraped pages 1, 3, 5
    already_scraped = {
        "https://books.toscrape.com/catalogue/page-1.html",
        "https://books.toscrape.com/catalogue/page-3.html",
        "https://books.toscrape.com/catalogue/page-5.html",
    }

    log.info("  Total URLs: {}", len(all_urls))
    log.info("  Already scraped: {}", len(already_scraped))

    async with BatchFetcher(concurrency=3, chunk_size=5) as fetcher:
        delta_results = await fetcher.fetch_batch(
            all_urls,
            skip_urls=already_scraped,  # only fetch pages 2 and 4
            prepare=False,
        )

    log.info("  Fetched (new only): {}", len(delta_results))
    for r in delta_results:
        log.info("  ✓ {}", r.url)

    # ── 3. BrowserFetcher — JavaScript-rendered page ──────────────────────────
    log.info("3. BrowserFetcher — fetching JS-rendered page with Playwright:")

    try:
        async with BrowserFetcher(headless=True, concurrency=2) as browser:
            log.info("  Launching Chromium browser...")
            start = time.time()

            result = await browser.async_fetch("https://books.toscrape.com")
            elapsed = time.time() - start

            log.info("  URL:          {}", result.url)
            log.info("  Status:       {}", result.status_code)
            log.info("  Success:      {}", result.success)
            log.info("  HTML length:  {} chars", len(result.html))
            log.info("  Time:         {:.2f}s", elapsed)
            log.info("  First 80:     {!r}", result.html[:80].strip())

            if result.metadata:
                log.info("  Metadata:     {}", result.metadata)

    except Exception as e:
        log.warning("  BrowserFetcher skipped — Playwright not installed: {}", str(e))
        log.info("  Run: pip install playwright && playwright install chromium")

    # ── 4. SessionManager — simulated auth flow ───────────────────────────────
    log.info("4. SessionManager — simulated login flow:")

    # quotes.toscrape.com/login is a real login page for demo purposes
    session_config = SessionConfig(
        login_url="https://quotes.toscrape.com/login",
        credentials={"username": "admin", "password": "admin"},
        success_check="Logout",         # this text appears when logged in
        expiry_signals=[401, "/login"],
        session_ttl=3600,
    )

    with SessionManager(session_config) as session:
        log.info("  Attempting login to quotes.toscrape.com...")
        login_success = session.login()
        log.info("  Login success: {}", login_success)

        if login_success:
            log.info("  Cookies stored: {}", list(session.get_cookies().keys()))
            log.info("  Cookie header: {}", session.get_cookie_header()[:60] + "...")

            # Fetch a protected page with the active session
            result = session.fetch("https://quotes.toscrape.com/")
            log.info("  Protected page: status={} chars={}",
                     result.status_code, len(result.html))
        else:
            log.info("  Login failed (expected if credentials wrong)")
            log.info("  Demonstrating cookie header format:")
            log.info("  Cookie: session_id=abc123; token=xyz789")

    # ── 5. Fetcher comparison summary ─────────────────────────────────────────
    log.info("5. Fetcher layer complete — summary:")
    log.info("  HttpFetcher     → sync, simple jobs, <20 URLs")
    log.info("  AsyncFetcher    → async, fast, 20-50 URLs")
    log.info("  BatchFetcher    → chunked async, 50+ URLs, progress + callbacks")
    log.info("  BrowserFetcher  → Playwright, JS-heavy sites, anti-bot")
    log.info("  SessionManager  → authenticated scraping, auto re-login")

    log.info("=" * 60)
    log.success("Day 5 complete — full fetcher layer built")
    log.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
