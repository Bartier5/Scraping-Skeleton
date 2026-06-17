import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from utils.logger import log
from utils.helpers import ensure_dir
from storage.sqlite_storage import SqliteStorage
from spiders.quotes_js_spider import QuotesJsSpider


async def main():
    ensure_dir("logs")
    ensure_dir("data")

    log.info("=" * 60)
    log.info("Quotes JS Spider — Playwright Demo")
    log.info("=" * 60)

    storage = SqliteStorage(
        db_path="data/quotes_js.db",
        table_name="quotes"
    )
    await storage.clear()

    spider = QuotesJsSpider(storage=storage)

    stats = await spider.run()

    log.info("Stats:")
    log.info("  URLs fetched:  {}", stats["urls_fetched"])
    log.info("  Items scraped: {}", stats["items_scraped"])
    log.info("  Items saved:   {}", stats["items_saved"])
    log.info("  Errors:        {}", stats["urls_failed"])

    count = await storage.count()
    sample = await storage.load(limit=3)
    log.info("DB total: {}", count)
    log.info("Sample:")
    for row in sample:
        log.info("  {} — {}", row.get("text", "")[:60], row.get("author"))


if __name__ == "__main__":
    asyncio.run(main())