# ── examples/day14_example.py ─────────────────────────────────────────────────
# Day 14 mini example — full end-to-end spider wiring demo.
# Shows ExampleSpider and BatchSpider running against real sites,
# with the complete pipeline from fetch to storage.
#
# Run with: python examples/day14_example.py

import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from utils.logger import log
from utils.helpers import ensure_dir
from storage.sqlite_storage import SqliteStorage
from storage.csv_storage import CsvStorage
from spiders.example_spider import ExampleSpider
from spiders.batch_spider import BatchSpider


async def main():
    ensure_dir("logs")
    ensure_dir("data")

    log.info("=" * 60)
    log.info("Day 14 — Full Spider Wiring Demo")
    log.info("=" * 60)

    # ── 1. ExampleSpider — single page ───────────────────────────────────────
    log.info("1. ExampleSpider — scraping a single catalogue page:")

    sqlite = SqliteStorage(
        db_path="data/day14_example.db",
        table_name="books"
    )
    await sqlite.clear()

    spider = ExampleSpider(storage=sqlite, concurrency=5)

    stats = await spider.run(urls=[
        "https://books.toscrape.com/catalogue/page-1.html"
    ])

    log.info("  Stats:")
    log.info("    URLs fetched:  {}", stats["urls_fetched"])
    log.info("    URLs failed:   {}", stats["urls_failed"])
    log.info("    Items scraped: {}", stats["items_scraped"])
    log.info("    Items saved:   {}", stats["items_saved"])
    log.info("    Started:       {}", stats["started_at"])
    log.info("    Finished:      {}", stats["finished_at"])

    # Verify data is in DB
    count = await sqlite.count()
    first_3 = await sqlite.load(limit=3)
    log.info("  DB row count: {}", count)
    log.info("  First 3 records:")
    for row in first_3:
        log.info("    {} | £{} | {}",
                 str(row.get("title", ""))[:35],
                 row.get("price"),
                 str(row.get("availability", "")).strip())

    # ── 2. ExampleSpider — multiple pages ─────────────────────────────────────
    log.info("2. ExampleSpider — scraping 3 pages concurrently:")

    sqlite2 = SqliteStorage(
        db_path="data/day14_multi.db",
        table_name="books"
    )
    await sqlite2.clear()

    spider2 = ExampleSpider(storage=sqlite2, concurrency=5)
    urls = ExampleSpider.build_page_urls(total_pages=3)

    log.info("  Scraping {} pages: {}", len(urls), [u.split("/")[-1] for u in urls])

    stats2 = await spider2.run(urls=urls)

    log.info("  Stats:")
    log.info("    URLs fetched:  {}", stats2["urls_fetched"])
    log.info("    Items scraped: {}", stats2["items_scraped"])
    log.info("    Items saved:   {}", stats2["items_saved"])
    log.info("  Total in DB: {}", await sqlite2.count())

    # ── 3. ExampleSpider → CSV output ─────────────────────────────────────────
    log.info("3. ExampleSpider — saving to CSV:")

    csv = CsvStorage(
        filepath="data/books_day14.csv",
        mode="overwrite"
    )

    spider3 = ExampleSpider(storage=csv, concurrency=5)
    stats3 = await spider3.run(urls=[
        "https://books.toscrape.com/catalogue/page-2.html"
    ])

    csv_count = await csv.count()
    log.info("  CSV rows saved: {}", csv_count)
    log.info("  File: data/books_day14.csv")

    # ── 4. BatchSpider — chunked with checkpointing ───────────────────────────
    log.info("4. BatchSpider — 5 pages with checkpointing:")

    batch_sqlite = SqliteStorage(
        db_path="data/day14_batch.db",
        table_name="books"
    )
    await batch_sqlite.clear()

    batch_spider = BatchSpider(
        storage=batch_sqlite,
        concurrency=5,
        chunk_size=3,
        delta_scraping=False,   # disable for demo — all pages are "new"
        checkpoint_db="data/day14_batch_checkpoints.db",
    )

    # Reset checkpoints for clean demo run
    await batch_spider.reset_checkpoints()

    batch_urls = ExampleSpider.build_page_urls(total_pages=5)
    log.info("  Batch scraping {} pages in chunks of 3...", len(batch_urls))

    batch_stats = await batch_spider.run(urls=batch_urls)

    log.info("  Batch stats:")
    log.info("    URLs total:             {}", batch_stats["urls_total"])
    log.info("    URLs fetched:           {}", batch_stats["urls_fetched"])
    log.info("    URLs failed:            {}", batch_stats["urls_failed"])
    log.info("    URLs skipped (cp):      {}", batch_stats["urls_skipped_checkpoint"])
    log.info("    URLs skipped (delta):   {}", batch_stats["urls_skipped_unchanged"])
    log.info("    Chunks processed:       {}", batch_stats["chunks_processed"])
    log.info("    Items scraped:          {}", batch_stats["items_scraped"])
    log.info("    Items saved:            {}", batch_stats["items_saved"])

    # Check checkpoint state
    cp_stats = await batch_spider.get_checkpoint_stats()
    log.info("  Checkpoint state:")
    log.info("    Total seen: {}", cp_stats["total_seen"])
    log.info("    Done:       {}", cp_stats["done"])
    log.info("    Failed:     {}", cp_stats["failed"])

    # ── 5. BatchSpider — resume demo ──────────────────────────────────────────
    log.info("5. BatchSpider — resume demo (run again, pages already checkpointed):")

    batch_spider2 = BatchSpider(
        storage=batch_sqlite,
        concurrency=5,
        chunk_size=3,
        delta_scraping=False,
        checkpoint_db="data/day14_batch_checkpoints.db",
    )

    resume_stats = await batch_spider2.run(urls=batch_urls)

    log.info("  Resume stats:")
    log.info("    URLs skipped (already done): {}",
             resume_stats["urls_skipped_checkpoint"])
    log.info("    URLs fetched (new work):     {}",
             resume_stats["urls_fetched"])
    log.info("  → All {} URLs already checkpointed — zero re-work",
             len(batch_urls))

    # ── 6. Full skeleton data flow summary ────────────────────────────────────
    log.info("6. Complete data flow summary:")
    log.info("  URL List")
    log.info("    ↓ url_utils.prepare_urls()    — normalize, validate, dedup")
    log.info("    ↓ AsyncFetcher.fetch_many()   — concurrent HTTP requests")
    log.info("    ↓ BS4Parser.parse()           — extract structured data")
    log.info("    ↓ DataCleaner.clean_items()   — normalize values")
    log.info("    ↓ DataTransformer.transform() — reshape for storage schema")
    log.info("    ↓ DataValidator.validate()    — enforce Pydantic schema")
    log.info("    ↓ SqliteStorage.save()        — persist to database")
    log.info("    ↓ CheckpointManager.mark_done() — record progress")
    log.info("  Done ✓")

    log.info("=" * 60)
    log.success("Day 14 complete — full end-to-end spider wiring working")
    log.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
