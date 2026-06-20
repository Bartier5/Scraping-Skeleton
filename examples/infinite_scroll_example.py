# ── examples/infinite_scroll_example.py ──────────────────────────────────────
# Test 2A — Infinite scroll example runner.
# Run with: python examples/infinite_scroll_example.py

import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from utils.logger import log
from utils.helpers import ensure_dir
from storage.sqlite_storage import SqliteStorage
from spiders.infinite_scroll_spider import InfiniteScrollSpider


async def main():
    ensure_dir("logs")
    ensure_dir("data")

    log.info("=" * 60)
    log.info("Test 2A — Infinite Scroll Spider")
    log.info("Target: quotes.toscrape.com/scroll")
    log.info("=" * 60)

    storage = SqliteStorage(
        db_path="data/infinite_scroll.db",
        table_name="quotes"
    )
    await storage.clear()

    spider = InfiniteScrollSpider(
        storage=storage,
        max_scrolls=20,   # quotes.toscrape.com/scroll has 10 pages = ~15 scrolls needed
    )

    log.info("Starting scroll — watch the quote count grow per scroll...")
    stats = await spider.run()

    log.info("=" * 60)
    log.info("Final stats:")
    log.info("  URLs processed: {}", stats["urls_total"])
    log.info("  Items scraped:  {}", stats["items_scraped"])
    log.info("  Items saved:    {}", stats["items_saved"])
    log.info("  Errors:         {}", stats["urls_failed"])

    count = await storage.count()
    log.info("  DB total:       {}", count)

    # Show sample
    sample = await storage.load(limit=5)
    log.info("Sample (first 5):")
    for row in sample:
        log.info("  {} — {}",
                 str(row.get("text", ""))[:55],
                 row.get("author"))

    # Show author distribution
    all_rows = await storage.load()
    authors = {}
    for row in all_rows:
        a = row.get("author", "Unknown")
        authors[a] = authors.get(a, 0) + 1

    log.info("Author distribution ({} unique):", len(authors))
    for author, cnt in sorted(authors.items(), key=lambda x: -x[1])[:5]:
        log.info("  {} — {} quotes", author, cnt)

    log.info("=" * 60)
    log.success("Test 2A complete")
    log.info("Query your results:")
    log.info("  python tools/query_db.py --db data/infinite_scroll.db --table quotes --count")
    log.info("  python tools/query_db.py --db data/infinite_scroll.db --table quotes --authors")
    log.info("  python tools/query_db.py --db data/infinite_scroll.db --table quotes --export csv")
    log.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
