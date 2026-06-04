# ── examples/day1_example.py ─────────────────────────────────────────────────
# Mini example that wires all Day 1 modules together in one script.
# Run this after the tests pass to see everything working as a unit.
#
# Run with: python examples/day1_example.py
import sys
import os
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import time                             # used to simulate work duration

from config.config import Config        # central settings
from utils.logger import log            # structured logger
from utils.retry import retry           # retry decorator
from utils.helpers import (
    clean_text,                         # whitespace normalizer
    get_domain,                         # extract domain from URL
    build_url,                          # construct URLs safely
    is_valid_url,                       # validate URLs before use
    hash_content,                       # MD5 hash for change detection
    slugify,                            # filename-safe string converter
    timestamp,                          # sortable datetime string
    ensure_dir,                         # create directories safely
    get_output_path,                    # build output file paths
)


def main():
    log.info("=" * 60)
    log.info("Day 1 — Scraper Skeleton Foundation Demo")
    log.info("=" * 60)

    # ── 1. Show Config values loaded from .env ────────────────────────────────
    log.info("Config values loaded:")
    log.debug("  TIMEOUT            = {}", Config.TIMEOUT)
    log.debug("  MAX_RETRIES        = {}", Config.MAX_RETRIES)
    log.debug("  CONCURRENCY        = {}", Config.CONCURRENCY)
    log.debug("  DELAY              = {}s", Config.DELAY_BETWEEN_REQUESTS)
    log.debug("  STORAGE_BACKEND    = {}", Config.STORAGE_BACKEND)
    log.debug("  LOG_LEVEL          = {}", Config.LOG_LEVEL)

    # ── 2. Logger — multiple levels ───────────────────────────────────────────
    log.info("Logger is working across all levels:")
    log.debug("  This is a DEBUG message — fine-grained detail")
    log.info("  This is an INFO message — general progress")
    log.warning("  This is a WARNING — something to keep an eye on")
    log.success("  This is a SUCCESS — loguru-specific level for good news")

    # ── 3. Helpers — URL utilities ────────────────────────────────────────────
    log.info("Testing URL helpers:")

    sample_urls = [
        "https://books.toscrape.com/catalogue/page-1.html",
        "https://api.example.com/v1/products",
        "not-a-real-url",
        "",
        "ftp://files.example.com",
    ]

    for url in sample_urls:
        valid = is_valid_url(url)
        domain = get_domain(url) if valid else "N/A"
        # log.info formats {} placeholders like .format() but lazily (only if logged)
        log.info("  URL: {:50} | valid={} | domain={}", url or "(empty)", valid, domain)

    # ── 4. Helpers — URL builder ──────────────────────────────────────────────
    log.info("Testing URL builder:")
    built = build_url(
        "https://api.example.com",
        "/search",
        {"q": "laptop", "page": 2, "sort": "price_asc"}
    )
    log.info("  Built URL: {}", built)

    # ── 5. Helpers — Text cleaning ────────────────────────────────────────────
    log.info("Testing text cleaners:")

    dirty_texts = [
        "  Lots   of   extra   spaces  ",
        "Line 1\n\n\nLine 2\n\tLine 3",
        "\t  Tabs and newlines everywhere \n ",
    ]

    for dirty in dirty_texts:
        cleaned = clean_text(dirty)
        log.info("  BEFORE: {!r}", dirty)
        log.info("  AFTER:  {!r}", cleaned)

    # ── 6. Helpers — Slugify ──────────────────────────────────────────────────
    log.info("Testing slugify:")
    titles = ["Latest iPhone Prices 2025!", "E-commerce Data & Analysis", "Books (Fiction)"]
    for title in titles:
        log.info("  '{}' → '{}'", title, slugify(title))

    # ── 7. Helpers — Content hashing (delta scraping preview) ─────────────────
    log.info("Testing content hashing:")
    page_v1 = "<html><body>Price: $99</body></html>"
    page_v2 = "<html><body>Price: $109</body></html>"   # price changed
    page_v3 = "<html><body>Price: $99</body></html>"    # same as v1

    h1 = hash_content(page_v1)
    h2 = hash_content(page_v2)
    h3 = hash_content(page_v3)

    log.info("  Page v1 hash: {}", h1)
    log.info("  Page v2 hash: {}", h2)
    log.info("  Page v3 hash: {}", h3)
    log.info("  v1 == v2? {} (price changed → different hash)", h1 == h2)
    log.info("  v1 == v3? {} (same content → same hash)", h1 == h3)

    # ── 8. Helpers — Timestamp and output paths ───────────────────────────────
    log.info("Testing timestamp and output path generation:")
    ts = timestamp()
    output_path = get_output_path(f"results_{ts}.csv")
    log.info("  Timestamp:   {}", ts)
    log.info("  Output path: {}", output_path)

    # ── 9. Retry decorator — real demonstration ───────────────────────────────
    log.info("Testing retry decorator:")

    attempt_count = {"n": 0}   # dict lets us mutate inside the nested function

    @retry(max_attempts=3, min_wait=0.1, max_wait=0.5)
    def flaky_operation():
        """Simulates a network call that fails twice then succeeds."""
        attempt_count["n"] += 1
        log.debug("  Attempt {} of 3...", attempt_count["n"])

        if attempt_count["n"] < 3:
            # Simulate a connection error on first two attempts
            raise ConnectionError(f"Simulated failure on attempt {attempt_count['n']}")

        log.success("  Succeeded on attempt {}!", attempt_count["n"])
        return "data received"

    try:
        result = flaky_operation()
        log.info("  Final result: '{}'", result)
    except Exception as e:
        log.error("  All retries exhausted: {}", e)

    # ── 10. Retry — exhausted retries ─────────────────────────────────────────
    log.info("Testing retry exhaustion (always fails):")

    @retry(max_attempts=2, min_wait=0.05, max_wait=0.1)
    def always_fails():
        raise TimeoutError("Server not responding")

    try:
        always_fails()
    except TimeoutError as e:
        # This is expected — retry gave up and re-raised the exception
        log.warning("  Caught expected exhaustion error: {}", e)

    # ── Done ──────────────────────────────────────────────────────────────────
    log.info("=" * 60)
    log.success("Day 1 complete — all foundation modules working correctly")
    log.info("Check logs/scraper.log for the full file output")
    log.info("=" * 60)


if __name__ == "__main__":
    # ensure_dir makes sure logs/ and data/ exist before anything runs
    ensure_dir("logs")
    ensure_dir("data")
    main()
