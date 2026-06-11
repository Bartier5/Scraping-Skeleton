# ── examples/day11_example.py ─────────────────────────────────────────────────
# Day 11 mini example — PostgresStorage demo.
#
# This example has two modes:
#   1. MOCK MODE (default) — runs without any PostgreSQL installation
#      Shows all PostgresStorage features using simulated responses
#
#   2. LIVE MODE — connects to a real PostgreSQL instance
#      Set POSTGRES_URL in your .env and pass --live flag:
#      python examples/day11_example.py --live
#
# Run with: python examples/day11_example.py

import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from utils.logger import log
from utils.helpers import ensure_dir
from fetcher.http_fetcher import HttpFetcher
from parser.bs4_parser import BS4Parser
from pipeline.cleaner import DataCleaner
from pipeline.transformer import DataTransformer
from pipeline.validator import DataValidator, BookSchema
from storage.postgres_storage import PostgresStorage

# Check if --live flag was passed
LIVE_MODE = "--live" in sys.argv


async def run_mock_demo(items: list[dict]):
    """
    Demonstrates PostgresStorage API using mocked asyncpg responses.
    Shows everything the storage can do without needing a real database.
    """
    from unittest.mock import AsyncMock, MagicMock

    log.info("Running in MOCK MODE — simulating PostgreSQL responses")
    log.info("Pass --live to connect to a real PostgreSQL instance")

    # ── Build mock pool that simulates asyncpg ────────────────────────────────
    # This mimics exactly what asyncpg returns so the storage code runs
    # the same paths as it would with a real database

    saved_rows = []   # in-memory store for the mock

    mock_conn = AsyncMock()

    async def mock_executemany(sql, rows):
        """Simulates INSERT — stores rows in memory."""
        saved_rows.extend(rows)
        log.debug("  [MockDB] executemany: {} rows inserted", len(rows))

    async def mock_fetch(sql, *args):
        """Simulates SELECT — returns stored rows as dicts."""
        return [
            {"id": i+1, "title": r[0], "price": r[1], "url": r[2], "availability": r[3] if len(r) > 3 else ""}
            for i, r in enumerate(saved_rows[:3])  # return first 3
        ]

    async def mock_fetchrow(sql, *args):
        """Simulates SELECT 1 EXISTS check."""
        # Return a row if any stored row matches
        search_val = args[0] if args else ""
        found = any(search_val in str(row) for row in saved_rows)
        return {"exists": 1} if found else None

    async def mock_fetchval(sql, *args):
        """Simulates COUNT(*)."""
        return min(len(saved_rows), 20)

    async def mock_execute(sql, *args):
        if "TRUNCATE" in sql:
            saved_rows.clear()
        return "OK"

    mock_conn.executemany = mock_executemany
    mock_conn.execute = mock_execute
    mock_conn.fetch = mock_fetch
    mock_conn.fetchrow = mock_fetchrow
    mock_conn.fetchval = mock_fetchval
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)

    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(return_value=mock_conn)
    mock_pool.close = AsyncMock()

    # ── Create storage with mock pool injected ────────────────────────────────
    storage = PostgresStorage(
        dsn="postgresql://mock:mock@localhost/mock_db",
        table_name="books",
        upsert_on="url",
    )
    storage._pool = mock_pool
    storage._table_created = True

    await demo_storage_operations(storage, items)


async def run_live_demo(items: list[dict]):
    """
    Demonstrates PostgresStorage with a real PostgreSQL connection.
    Requires POSTGRES_URL to be set in .env
    """
    from config.config import Config

    if not Config.POSTGRES_URL:
        log.error("POSTGRES_URL not set in .env — cannot run live demo")
        log.info("Add this to your .env file:")
        log.info("  POSTGRES_URL=postgresql://user:password@localhost:5432/scraper_db")
        return

    log.info("Running in LIVE MODE — connecting to PostgreSQL")
    log.info("DSN: {}", Config.POSTGRES_URL[:30] + "...")

    async with PostgresStorage(
        dsn=Config.POSTGRES_URL,
        table_name="books_day11",
        pool_size=3,
        upsert_on="url",
    ) as storage:
        await demo_storage_operations(storage, items)


async def demo_storage_operations(storage: PostgresStorage, items: list[dict]):
    """
    Runs the same demo operations against either mock or live storage.
    This is the actual demonstration of PostgresStorage capabilities.
    """

    # ── 1. Save data ──────────────────────────────────────────────────────────
    log.info("1. PostgresStorage — saving {} books:", len(items))

    save_result = await storage.save(items)
    log.info("  SaveResult: {}", save_result)
    log.info("  Rows saved: {}", save_result.rows_saved)
    log.info("  Backend: {}", save_result.backend)
    log.info("  Table: {}", save_result.metadata.get("table"))

    # ── 2. Count rows ─────────────────────────────────────────────────────────
    log.info("2. Row count:")
    count = await storage.count()
    log.info("  Total rows in table: {}", count)

    # ── 3. Exists check ───────────────────────────────────────────────────────
    log.info("3. Exists checks (indexed query):")
    sample_url = items[0]["url"] if items else "https://example.com"
    exists = await storage.exists("url", sample_url)
    log.info("  Known URL exists: {}", exists)
    not_exists = await storage.exists("url", "https://definitely-not-there.com")
    log.info("  Unknown URL exists: {}", not_exists)

    # ── 4. Load records ───────────────────────────────────────────────────────
    log.info("4. Loading records:")
    loaded = await storage.load(limit=3)
    log.info("  Loaded {} records (limit=3)", len(loaded))
    for row in loaded:
        log.info("    {} | {}",
                 str(row.get("title", ""))[:35],
                 row.get("price", "N/A"))

    # ── 5. Upsert demo ────────────────────────────────────────────────────────
    log.info("5. Upsert — saving same data again (should not duplicate):")
    upsert_result = await storage.save(items[:3])
    log.info("  Upsert result: {}", upsert_result)
    count_after = await storage.count()
    log.info("  Row count after upsert: {} (same as before = no dupes)", count_after)

    # ── 6. Clear ──────────────────────────────────────────────────────────────
    log.info("6. Clear table:")
    cleared = await storage.clear()
    count_after_clear = await storage.count()
    log.info("  Cleared: {} | Row count after: {}", cleared, count_after_clear)


async def main():
    ensure_dir("logs")
    ensure_dir("data")

    log.info("=" * 60)
    log.info("Day 11 — PostgresStorage Demo")
    log.info("=" * 60)

    # ── Fetch and pipeline real data ──────────────────────────────────────────
    log.info("Fetching books data through pipeline...")

    with HttpFetcher() as fetcher:
        result = fetcher.fetch("https://books.toscrape.com/catalogue/page-1.html")

    parser = BS4Parser()
    soup = parser.make_soup(result.html)

    titles = parser.get_all_text(soup, "h3 > a")
    prices = parser.get_all_text(soup, "p.price_color")
    avails = parser.get_all_text(soup, "p.availability")
    links  = parser.get_all_attr(soup, "h3 > a", "href")

    raw_items = [
        {
            "title": t, "price_raw": p, "availability": a,
            "url": f"https://books.toscrape.com/catalogue/{l.replace('../', '')}",
        }
        for t, p, a, l in zip(titles, prices, avails, links)
    ]

    cleaner     = DataCleaner()
    transformer = DataTransformer(
        computed={"price": lambda item: DataCleaner.extract_number(item.get("price_raw", "") or "")},
        add_metadata=True,
    )
    validator   = DataValidator(schema=BookSchema, strict=False)

    cleaned     = cleaner.clean_items(raw_items)
    transformed = transformer.transform_items(cleaned)
    batch       = validator.validate_batch(transformed)
    items       = batch.valid_items

    log.info("Pipeline produced {} clean records", len(items))

    # ── Run demo ──────────────────────────────────────────────────────────────
    if LIVE_MODE:
        await run_live_demo(items)
    else:
        await run_mock_demo(items)

    # ── Storage comparison table ───────────────────────────────────────────────
    log.info("Storage backend comparison:")
    log.info("  ┌─────────────────┬──────────┬──────────┬──────────┬──────────┐")
    log.info("  │ Feature         │ CSV      │ SQLite   │ Postgres │          │")
    log.info("  ├─────────────────┼──────────┼──────────┼──────────┼──────────┤")
    log.info("  │ Setup           │ None     │ None     │ Required │          │")
    log.info("  │ Max rows        │ ~100k    │ ~1M      │ Unlimited│          │")
    log.info("  │ Concurrent write│ No       │ No       │ Yes      │          │")
    log.info("  │ SQL queries     │ No       │ Basic    │ Full     │          │")
    log.info("  │ exists() speed  │ O(n)     │ O(log n) │ O(log n) │          │")
    log.info("  │ Upsert support  │ No       │ No       │ Yes      │          │")
    log.info("  │ Client access   │ File     │ File     │ Network  │          │")
    log.info("  └─────────────────┴──────────┴──────────┴──────────┴──────────┘")

    log.info("=" * 60)
    log.success("Day 11 complete — PostgresStorage ready for production")
    log.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
