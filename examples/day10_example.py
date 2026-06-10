# ── examples/day10_example.py ─────────────────────────────────────────────────
# Day 10 mini example — CSV storage, SQLite storage, and checkpointing.
# Shows real data being saved, loaded, deduplicated, and checkpointed.
#
# Run with: python examples/day10_example.py

import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from utils.logger import log
from utils.helpers import ensure_dir, hash_content
from fetcher.http_fetcher import HttpFetcher
from parser.bs4_parser import BS4Parser
from pipeline.cleaner import DataCleaner
from pipeline.transformer import DataTransformer
from pipeline.validator import DataValidator, BookSchema
from storage.csv_storage import CsvStorage
from storage.sqlite_storage import SqliteStorage
from storage.checkpoint_manager import CheckpointManager


async def main():
    ensure_dir("logs")
    ensure_dir("data")

    log.info("=" * 60)
    log.info("Day 10 — Storage Layer Demo")
    log.info("=" * 60)

    # ── Fetch and run through pipeline to get clean data ──────────────────────
    log.info("Fetching books data through full pipeline...")

    with HttpFetcher() as fetcher:
        result = fetcher.fetch("https://books.toscrape.com/catalogue/page-1.html")

    parser = BS4Parser()
    soup = parser.make_soup(result.html)

    titles  = parser.get_all_text(soup, "h3 > a")
    prices  = parser.get_all_text(soup, "p.price_color")
    avails  = parser.get_all_text(soup, "p.availability")
    links   = parser.get_all_attr(soup, "h3 > a", "href")

    raw_items = [
        {
            "title": t, "price_raw": p, "availability": a,
            "url": f"https://books.toscrape.com/catalogue/{l.replace('../', '')}",
        }
        for t, p, a, l in zip(titles, prices, avails, links)
    ]

    cleaner = DataCleaner()
    transformer = DataTransformer(
        computed={"price": lambda item: DataCleaner.extract_number(item.get("price_raw", "") or "")},
        add_metadata=True,
    )
    validator = DataValidator(schema=BookSchema, strict=False)

    cleaned     = cleaner.clean_items(raw_items)
    transformed = transformer.transform_items(cleaned)
    batch       = validator.validate_batch(transformed)
    items       = batch.valid_items

    log.info("Pipeline produced {} clean records", len(items))

    # ── 1. CsvStorage ─────────────────────────────────────────────────────────
    log.info("1. CsvStorage — saving {} books to CSV:", len(items))

    csv_storage = CsvStorage(
        filepath="data/books_storage_demo.csv",
        mode="overwrite",
    )

    save_result = await csv_storage.save(items)
    log.info("  SaveResult: {}", save_result)
    log.info("  Rows saved: {}", save_result.rows_saved)
    log.info("  File: {}", save_result.metadata.get("filepath"))

    # Load back and verify
    loaded = await csv_storage.load()
    log.info("  Loaded back: {} rows", len(loaded))

    # Exists check
    sample_url = items[0]["url"]
    exists = await csv_storage.exists("url", sample_url)
    log.info("  Exists check (known URL): {}", exists)
    not_exists = await csv_storage.exists("url", "https://not-in-file.com")
    log.info("  Exists check (unknown URL): {}", not_exists)

    # Count
    count = await csv_storage.count()
    log.info("  Row count: {}", count)

    # Append mode demo
    csv_append = CsvStorage(filepath="data/books_append_demo.csv", mode="append")
    await csv_append.save(items[:5])
    await csv_append.save(items[5:10])
    append_count = await csv_append.count()
    log.info("  Append mode — saved in 2 batches, total: {}", append_count)

    # ── 2. SqliteStorage ──────────────────────────────────────────────────────
    log.info("2. SqliteStorage — saving to local database:")

    sqlite = SqliteStorage(
        db_path="data/books_demo.db",
        table_name="books",
    )

    # Clear any previous data
    await sqlite.clear()

    sqlite_result = await sqlite.save(items)
    log.info("  SaveResult: {}", sqlite_result)
    log.info("  Rows saved: {}", sqlite_result.rows_saved)

    # Count
    count = await sqlite.count()
    log.info("  DB row count: {}", count)

    # Exists check — SQLite uses indexed query, much faster than CSV
    exists = await sqlite.exists("url", sample_url)
    log.info("  Exists (indexed query): {}", exists)

    # Load with limit
    first_3 = await sqlite.load(limit=3)
    log.info("  First 3 records from DB:")
    for row in first_3:
        log.info("    {} | {}", row.get("title", "")[:35], row.get("price"))

    # ── 3. SQLite Checkpointing ────────────────────────────────────────────────
    log.info("3. SqliteStorage checkpointing — resumable scraping:")

    # Simulate a scrape job that gets interrupted
    all_urls = [item["url"] for item in items[:8]]

    # Simulate: first run scraped the first 5
    for url in all_urls[:5]:
        await sqlite.checkpoint(url)

    checkpoint_count = await sqlite.get_checkpoint_count()
    log.info("  Checkpointed {} URLs after first run", checkpoint_count)

    # Simulate: second run — check which URLs still need processing
    pending = []
    for url in all_urls:
        if not await sqlite.is_checkpointed(url):
            pending.append(url)

    log.info("  URLs remaining after resume: {}", len(pending))
    log.info("  Pending: {}", [u.split("/")[-2] for u in pending])

    # ── 4. CheckpointManager — full delta scraping demo ───────────────────────
    log.info("4. CheckpointManager — delta scraping with content hashing:")

    manager = CheckpointManager(db_path="data/checkpoints_demo.db")
    await manager.init()
    await manager.reset()   # fresh start for demo

    scrape_urls = [item["url"] for item in items[:6]]

    # Simulate first full scrape
    log.info("  First scrape run — processing all {} URLs:", len(scrape_urls))
    for url in scrape_urls:
        # Simulate fetching and hashing content
        fake_html = f"<html>content for {url}</html>"
        content_hash = hash_content(fake_html)
        await manager.mark_done(url, content_hash=content_hash)
        log.debug("  Checkpointed: {}", url.split("/")[-2])

    stats = await manager.get_stats()
    log.info("  After first run: {}", stats)

    # Simulate second run — check what needs re-processing
    log.info("  Second scrape run — checking for changes:")

    # Simulate: most pages unchanged, one page has new content
    changed_url = scrape_urls[2]
    new_content = "<html>UPDATED content for this page</html>"
    new_hash = hash_content(new_content)

    needs_reprocess = []
    for url in scrape_urls:
        # Simulate fetching the page again
        if url == changed_url:
            current_hash = new_hash       # this page changed
        else:
            current_hash = hash_content(f"<html>content for {url}</html>")  # unchanged

        changed = await manager.has_changed(url, current_hash)
        if changed:
            needs_reprocess.append(url)
            log.info("  ↻ Changed: {} → will re-process", url.split("/")[-2])
        else:
            log.debug("  ✓ Unchanged: {}", url.split("/")[-2])

    log.info("  Pages needing re-process: {}", len(needs_reprocess))

    # ── 5. get_pending — batch efficiency demo ────────────────────────────────
    log.info("5. get_pending — efficient batch checkpoint check:")

    manager2 = CheckpointManager(db_path="data/checkpoints_demo2.db")
    await manager2.init()

    all_100_urls = [f"https://example.com/page-{i}" for i in range(1, 11)]

    # Mark first 7 as done
    for url in all_100_urls[:7]:
        await manager2.mark_done(url)

    # One batch call instead of 10 individual is_done() calls
    pending = await manager2.get_pending(all_100_urls)
    log.info("  Total URLs: {} | Done: {} | Pending: {}",
             len(all_100_urls), 7, len(pending))
    log.info("  Pending pages: {}", [u.split("-")[-1] for u in pending])

    # ── 6. Storage layer summary ──────────────────────────────────────────────
    log.info("6. Storage layer summary:")
    log.info("  CsvStorage        → flat files, Excel-friendly, simple jobs")
    log.info("  SqliteStorage     → local DB, fast queries, resumable scrapes")
    log.info("  CheckpointManager → delta scraping, change detection, progress tracking")
    log.info("  PostgresStorage   → coming Day 11, production-grade")

    log.info("=" * 60)
    log.success("Day 10 complete — storage layer working end-to-end")
    log.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
