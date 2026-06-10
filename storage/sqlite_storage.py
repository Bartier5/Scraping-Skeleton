# ── storage/sqlite_storage.py ─────────────────────────────────────────────────
# SQLite storage backend — local database with checkpointing support.
#
# When to use SQLite storage:
#   - Medium-sized scrape jobs (up to ~1M rows comfortably)
#   - Jobs that need to be resumable (checkpointing)
#   - When you need to query scraped data without setting up PostgreSQL
#   - Delta scraping — easily check if a URL was already scraped
#
# Key advantage over CSV:
#   exists() is a fast indexed query instead of a full file scan.
#   count() is instant. Resumable scrapes are trivial.
#
# Uses aiosqlite for async non-blocking database operations.
# Inherits from BaseStorage.

import aiosqlite
import json
import os
from typing import Any, Optional
from datetime import datetime

from storage.base_storage import BaseStorage, SaveResult
from utils.logger import log
from utils.helpers import ensure_dir
from pathlib import Path


class SqliteStorage(BaseStorage):
    """
    Async SQLite storage backend with checkpointing support.

    Creates a table automatically on first use based on the fields
    in the first item saved. The table schema is inferred — no need
    to define it upfront.

    Checkpointing:
        A separate 'checkpoints' table tracks which URLs have been
        scraped. Before fetching a URL, call is_checkpointed(url).
        After processing, call checkpoint(url). This enables resumable
        scrape runs that pick up where they left off.
    """

    def __init__(
        self,
        db_path: str = "data/scraper.db",
        table_name: str = "scraped_data",
        config: dict = None,
    ):
        """
        Args:
            db_path:    path to the SQLite database file
                        created automatically if it doesn't exist
            table_name: name of the table to store scraped records
        """
        super().__init__(config)
        self.db_path = db_path
        self.table_name = table_name
        self._table_created = False     # track if table has been initialized

        # Ensure parent directory exists
        ensure_dir(str(Path(db_path).parent))
        log.debug("SqliteStorage initialized (db={}, table={})", db_path, table_name)

    async def _get_connection(self) -> aiosqlite.Connection:
        """
        Returns an aiosqlite connection to the database.
        aiosqlite connections must be used as async context managers.

        Usage:
            async with await self._get_connection() as conn:
                await conn.execute(...)
        """
        return aiosqlite.connect(self.db_path)

    async def _ensure_table(self, columns: list[str]) -> None:
        """
        Creates the data table if it doesn't exist.
        Uses CREATE TABLE IF NOT EXISTS so it's safe to call repeatedly.

        All columns are stored as TEXT — SQLite is flexible with types
        and we've already done type casting in the pipeline.

        Args:
            columns: list of column names from the first saved item
        """
        if self._table_created:
            return   # already initialized this session

        # Build column definitions — all TEXT, with id as auto-increment primary key
        col_defs = ", ".join(f'"{col}" TEXT' for col in columns)

        create_sql = f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                {col_defs},
                inserted_at TEXT DEFAULT (datetime('now'))
            )
        """

        # Also create the checkpoints table for resumable scraping
        checkpoint_sql = """
            CREATE TABLE IF NOT EXISTS checkpoints (
                url TEXT PRIMARY KEY,
                content_hash TEXT,
                scraped_at TEXT DEFAULT (datetime('now'))
            )
        """

        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(create_sql)
            await conn.execute(checkpoint_sql)
            # Create index on URL column if it exists — speeds up exists() checks
            if "url" in columns:
                await conn.execute(
                    f'CREATE INDEX IF NOT EXISTS idx_{self.table_name}_url '
                    f'ON {self.table_name} ("url")'
                )
            await conn.commit()

        self._table_created = True
        log.debug("SqliteStorage: table '{}' ready", self.table_name)

    async def save(self, data: list[dict], **kwargs) -> SaveResult:
        """
        Saves a list of dicts to the SQLite table.
        Creates the table on first call based on the item structure.

        Args:
            data:     list of dicts to save
            **kwargs: optional overrides

        Returns:
            SaveResult with rows_saved count
        """
        if not data:
            return SaveResult(success=True, rows_saved=0, backend="sqlite")

        try:
            columns = list(data[0].keys())
            await self._ensure_table(columns)

            # Build parameterized INSERT statement
            # Using ? placeholders prevents SQL injection
            col_str = ", ".join(f'"{c}"' for c in columns)
            placeholder_str = ", ".join("?" for _ in columns)
            insert_sql = f'INSERT INTO {self.table_name} ({col_str}) VALUES ({placeholder_str})'

            # Convert each dict to a tuple of values in column order
            # Convert non-string values to JSON strings for storage
            rows = []
            for item in data:
                row = tuple(
                    json.dumps(v) if isinstance(v, (list, dict)) else str(v) if v is not None else None
                    for v in (item.get(col) for col in columns)
                )
                rows.append(row)

            async with aiosqlite.connect(self.db_path) as conn:
                # executemany inserts all rows in a single transaction — much faster
                await conn.executemany(insert_sql, rows)
                await conn.commit()

            log.info("SqliteStorage: saved {} rows to '{}'", len(data), self.table_name)
            return SaveResult(
                success=True,
                rows_saved=len(data),
                backend="sqlite",
                metadata={"table": self.table_name, "db": self.db_path},
            )

        except Exception as e:
            return self.make_error_result(e, backend="sqlite")

    async def load(self, limit: int = None, **kwargs) -> list[dict]:
        """
        Loads records from the SQLite table as a list of dicts.

        Args:
            limit: max number of rows to return (None = all)
            **kwargs: optional WHERE clause:
                      - where (str): SQL WHERE condition e.g. "price > 10"

        Returns:
            list of dicts, one per row (excludes id and inserted_at)
        """
        try:
            where = kwargs.get("where", "")
            limit_clause = f"LIMIT {limit}" if limit else ""
            where_clause = f"WHERE {where}" if where else ""

            sql = f"SELECT * FROM {self.table_name} {where_clause} {limit_clause}"

            async with aiosqlite.connect(self.db_path) as conn:
                conn.row_factory = aiosqlite.Row   # returns dict-like rows
                async with conn.execute(sql) as cursor:
                    rows = await cursor.fetchall()
                    # Convert Row objects to plain dicts
                    return [dict(row) for row in rows]

        except Exception as e:
            log.error("SqliteStorage.load failed: {}", str(e))
            return []

    async def exists(self, key: str, value: Any) -> bool:
        """
        Checks if any row has the given key=value using an indexed query.
        Much faster than CsvStorage.exists() which scans the whole file.

        Args:
            key:   column name to check
            value: value to look for

        Returns:
            True if any matching row exists
        """
        try:
            sql = f'SELECT 1 FROM {self.table_name} WHERE "{key}" = ? LIMIT 1'
            async with aiosqlite.connect(self.db_path) as conn:
                async with conn.execute(sql, (str(value),)) as cursor:
                    row = await cursor.fetchone()
                    return row is not None

        except Exception as e:
            log.error("SqliteStorage.exists failed: {}", str(e))
            return False

    async def clear(self) -> bool:
        """Drops and recreates the data table. Preserves checkpoints."""
        try:
            async with aiosqlite.connect(self.db_path) as conn:
                await conn.execute(f"DROP TABLE IF EXISTS {self.table_name}")
                await conn.commit()
            self._table_created = False
            log.debug("SqliteStorage: cleared table '{}'", self.table_name)
            return True
        except Exception as e:
            log.error("SqliteStorage.clear failed: {}", str(e))
            return False

    async def count(self) -> int:
        """Returns total row count — instant via SQLite COUNT(*)."""
        try:
            async with aiosqlite.connect(self.db_path) as conn:
                async with conn.execute(f"SELECT COUNT(*) FROM {self.table_name}") as cursor:
                    row = await cursor.fetchone()
                    return row[0] if row else 0
        except Exception:
            return 0

    # ── Checkpointing ─────────────────────────────────────────────────────────

    async def checkpoint(self, url: str, content_hash: str = "") -> None:
        """
        Records a URL as scraped in the checkpoints table.
        Call this after successfully processing a URL.

        Args:
            url:          the scraped URL
            content_hash: optional MD5 hash of page content for delta scraping
                          store it now, compare on next run to detect changes
        """
        try:
            # Ensure checkpoints table exists
            async with aiosqlite.connect(self.db_path) as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS checkpoints (
                        url TEXT PRIMARY KEY,
                        content_hash TEXT,
                        scraped_at TEXT DEFAULT (datetime('now'))
                    )
                """)
                # INSERT OR REPLACE updates the record if URL already exists
                await conn.execute(
                    "INSERT OR REPLACE INTO checkpoints (url, content_hash) VALUES (?, ?)",
                    (url, content_hash)
                )
                await conn.commit()
        except Exception as e:
            log.error("SqliteStorage.checkpoint failed: {}", str(e))

    async def is_checkpointed(self, url: str) -> bool:
        """
        Returns True if this URL has already been scraped.
        Use before fetching to implement resumable scrapes.

        Usage in a spider:
            if await storage.is_checkpointed(url):
                continue   # skip — already done
            result = await fetcher.async_fetch(url)
            await storage.checkpoint(url)
        """
        try:
            async with aiosqlite.connect(self.db_path) as conn:
                async with conn.execute(
                    "SELECT 1 FROM checkpoints WHERE url = ? LIMIT 1",
                    (url,)
                ) as cursor:
                    return await cursor.fetchone() is not None
        except Exception:
            return False

    async def get_checkpoint_count(self) -> int:
        """Returns how many URLs have been checkpointed."""
        try:
            async with aiosqlite.connect(self.db_path) as conn:
                async with conn.execute("SELECT COUNT(*) FROM checkpoints") as cursor:
                    row = await cursor.fetchone()
                    return row[0] if row else 0
        except Exception:
            return 0

    async def clear_checkpoints(self) -> bool:
        """Clears all checkpoints — use when starting a fresh scrape run."""
        try:
            async with aiosqlite.connect(self.db_path) as conn:
                await conn.execute("DELETE FROM checkpoints")
                await conn.commit()
            log.debug("SqliteStorage: checkpoints cleared")
            return True
        except Exception as e:
            log.error("SqliteStorage.clear_checkpoints failed: {}", str(e))
            return False
