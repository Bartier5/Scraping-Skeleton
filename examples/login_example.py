# ── examples/login_example.py ─────────────────────────────────────────────────
# Test 2B — Login wall example runner.
# Run with: python examples/login_example.py

import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from utils.logger import log
from utils.helpers import ensure_dir
from storage.sqlite_storage import SqliteStorage
from spiders.login_spider import LoginSpider


async def main():
    ensure_dir("logs")
    ensure_dir("data")

    log.info("=" * 60)
    log.info("Test 2B — Login Wall Spider")
    log.info("Target: quotes.toscrape.com/login")
    log.info("=" * 60)

    storage = SqliteStorage(
        db_path="data/login_quotes.db",
        table_name="quotes"
    )
    await storage.clear()

    spider = LoginSpider(
        username="user",
        password="password",
        storage=storage,
    )

    log.info("Attempting login and scraping protected pages...")
    stats = await spider.run()

    log.info("=" * 60)
    log.info("Final stats:")
    log.info("  Items scraped: {}", stats["items_scraped"])
    log.info("  Items saved:   {}", stats["items_saved"])
    log.info("  Errors:        {}", stats["urls_failed"])

    count = await storage.count()
    sample = await storage.load(limit=3)

    log.info("DB total: {}", count)
    log.info("Sample:")
    for row in sample:
        log.info("  {} — {}",
                 str(row.get("text", ""))[:55],
                 row.get("author"))

    log.info("=" * 60)
    log.success("Test 2B complete")
    log.info("Query results:")
    log.info("  python tools/query_db.py --db data/login_quotes.db --table quotes --count")
    log.info("  python tools/query_db.py --db data/login_quotes.db --table quotes --authors")
    log.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())