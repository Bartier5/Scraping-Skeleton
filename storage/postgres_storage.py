# ── storage/postgres_storage.py ───────────────────────────────────────────────
# PostgreSQL storage backend — production-grade async database storage.
#
# When to use PostgreSQL over SQLite:
#   - Multiple scrapers writing simultaneously (SQLite locks on write)
#   - Data volumes over ~1M rows (SQLite starts slowing down)
#   - Client needs to query data via their own tools (Tableau, Metabase)
#   - Retainer work where data accumulates over months
#   - When you need proper indexes, views, or stored procedures
#
# Setup:
#   1. Install PostgreSQL locally or use a cloud instance
#   2. Create a database: createdb scraper_db
#   3. Set POSTGRES_URL in your .env file:
#      POSTGRES_URL=postgresql://user:password@localhost:5432/scraper_db
#
# Uses asyncpg — the fastest async PostgreSQL driver for Python.
# Falls back gracefully if asyncpg is not installed.

import json
import asyncio
from typing import Any, Optional

from storage.base_storage import BaseStorage, SaveResult
from config.config import Config
from utils.logger import log

try:
    import asyncpg
    ASYNCPG_AVAILABLE = True
except ImportError:
    ASYNCPG_AVAILABLE = False
    log.warning("asyncpg not installed — PostgresStorage unavailable. Run: pip install asyncpg")


class PostgresStorage(BaseStorage):
    """
    Async PostgreSQL storage backend using asyncpg.

    Creates tables automatically on first use — schema is inferred
    from the first item's keys, same pattern as SqliteStorage.

    Connection pooling:
        asyncpg uses a connection pool — a set of pre-opened connections
        that are reused across requests. This is much faster than opening
        a new connection for every save() call. Pool size is configurable.

    Upsert support:
        Optional upsert mode — INSERT OR UPDATE on conflict with a
        specified unique column (e.g. url). Prevents duplicate rows
        when running the same scrape job multiple times.
    """

    def __init__(
        self,
        dsn: str = None,                # connection string — overrides Config
        table_name: str = "scraped_data",
        pool_size: int = 5,             # number of connections in the pool
        upsert_on: str = None,          # column to use for upsert conflict detection
        config: dict = None,
    ):
        """
        Args:
            dsn:        PostgreSQL connection string.
                        Format: postgresql://user:pass@host:port/dbname
                        Defaults to Config.POSTGRES_URL from .env
            table_name: name of the table to store scraped records
            pool_size:  how many connections to keep open in the pool
            upsert_on:  if set, use INSERT ... ON CONFLICT DO UPDATE
                        instead of plain INSERT. Set to "url" to prevent
                        duplicate rows when re-running scrapes.
        """
        super().__init__(config)

        if not ASYNCPG_AVAILABLE:
            raise RuntimeError(
                "asyncpg is required for PostgresStorage. "
                "Install it with: pip install asyncpg"
            )

        self.dsn = dsn or Config.POSTGRES_URL
        self.table_name = table_name
        self.pool_size = pool_size
        self.upsert_on = upsert_on
        self._pool = None               # connection pool — created lazily
        self._table_created = False

        if not self.dsn:
            log.warning(
                "PostgresStorage: no DSN provided. "
                "Set POSTGRES_URL in your .env file."
            )

        log.debug(
            "PostgresStorage initialized (table={}, pool_size={}, upsert_on={})",
            table_name, pool_size, upsert_on
        )

    async def _get_pool(self) -> "asyncpg.Pool":
        """
        Returns the asyncpg connection pool, creating it if needed.

        asyncpg.create_pool() opens pool_size connections to PostgreSQL
        and keeps them open for reuse. Much faster than creating a new
        connection on every database operation.

        Lazy initialization — pool is only created when first needed.
        """
        if self._pool is None:
            if not self.dsn:
                raise RuntimeError(
                    "PostgresStorage: POSTGRES_URL not configured. "
                    "Set it in your .env file."
                )
            self._pool = await asyncpg.create_pool(
                self.dsn,
                min_size=1,                 # always keep at least 1 connection open
                max_size=self.pool_size,    # max connections in the pool
                command_timeout=60,         # timeout for any single SQL command
            )
            log.debug("PostgresStorage: connection pool created (size={})", self.pool_size)

        return self._pool

    async def _ensure_table(self, columns: list[str]) -> None:
        """
        Creates the data table if it doesn't exist.
        All columns stored as TEXT — type casting happens in the pipeline.

        Creates a GIN index on the url column if present for fast lookups.
        """
        if self._table_created:
            return

        # Build column definitions
        col_defs = ", ".join(f'"{col}" TEXT' for col in columns)

        create_sql = f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                id          BIGSERIAL PRIMARY KEY,
                {col_defs},
                inserted_at TIMESTAMPTZ DEFAULT NOW()
            )
        """

        pool = await self._get_pool()
        async with pool.acquire() as conn:
            # acquire() gets a connection from the pool
            # released back to pool automatically when the with block exits
            await conn.execute(create_sql)

            # Create index on url column for fast exists() checks
            if "url" in columns:
                await conn.execute(f"""
                    CREATE INDEX IF NOT EXISTS idx_{self.table_name}_url
                    ON {self.table_name} (url)
                """)

        self._table_created = True
        log.debug("PostgresStorage: table '{}' ready", self.table_name)

    async def save(self, data: list[dict], **kwargs) -> SaveResult:
        """
        Saves a list of dicts to the PostgreSQL table.

        In normal mode: INSERT INTO table (cols) VALUES (...)
        In upsert mode: INSERT ... ON CONFLICT (upsert_on) DO UPDATE SET ...

        Upsert mode prevents duplicate rows when running the same scrape
        job multiple times — existing rows are updated instead of rejected.

        Uses executemany() for batch inserts — much faster than individual
        INSERT calls because it sends all rows in a single network round trip.

        Args:
            data:     list of dicts to save
            **kwargs: optional overrides

        Returns:
            SaveResult with rows_saved count
        """
        if not data:
            return SaveResult(success=True, rows_saved=0, backend="postgres")

        try:
            columns = list(data[0].keys())
            await self._ensure_table(columns)

            pool = await self._get_pool()

            # Convert dicts to list of tuples in column order
            # Non-string values converted to string for TEXT storage
            rows = []
            for item in data:
                row = tuple(
                    json.dumps(v) if isinstance(v, (list, dict))
                    else str(v) if v is not None
                    else None
                    for v in (item.get(col) for col in columns)
                )
                rows.append(row)

            # Build parameterized SQL with $1, $2... placeholders
            # (PostgreSQL uses $N placeholders, not ? like SQLite)
            col_str = ", ".join(f'"{c}"' for c in columns)
            placeholder_str = ", ".join(f"${i+1}" for i in range(len(columns)))

            if self.upsert_on and self.upsert_on in columns:
                # Upsert: on conflict with the specified column, update all other columns
                update_cols = [c for c in columns if c != self.upsert_on]
                update_str = ", ".join(
                    f'"{c}" = EXCLUDED."{c}"' for c in update_cols
                )
                sql = f"""
                    INSERT INTO {self.table_name} ({col_str})
                    VALUES ({placeholder_str})
                    ON CONFLICT ("{self.upsert_on}") DO UPDATE SET {update_str}
                """
            else:
                sql = f"""
                    INSERT INTO {self.table_name} ({col_str})
                    VALUES ({placeholder_str})
                """

            async with pool.acquire() as conn:
                # executemany sends all rows in a single transaction
                await conn.executemany(sql, rows)

            log.info(
                "PostgresStorage: saved {} rows to '{}'",
                len(data), self.table_name
            )
            return SaveResult(
                success=True,
                rows_saved=len(data),
                backend="postgres",
                metadata={"table": self.table_name},
            )

        except Exception as e:
            return self.make_error_result(e, backend="postgres")

    async def load(self, limit: int = None, **kwargs) -> list[dict]:
        """
        Loads records from the PostgreSQL table.

        Args:
            limit:    max rows to return
            **kwargs: optional:
                      - where (str): SQL WHERE clause e.g. "price > '10'"
                      - order_by (str): ORDER BY clause e.g. "inserted_at DESC"

        Returns:
            list of dicts
        """
        try:
            where     = kwargs.get("where", "")
            order_by  = kwargs.get("order_by", "id ASC")
            limit_sql = f"LIMIT {limit}" if limit else ""
            where_sql = f"WHERE {where}" if where else ""

            sql = f"""
                SELECT * FROM {self.table_name}
                {where_sql}
                ORDER BY {order_by}
                {limit_sql}
            """

            pool = await self._get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch(sql)
                # asyncpg Record objects — convert to plain dicts
                return [dict(row) for row in rows]

        except Exception as e:
            log.error("PostgresStorage.load failed: {}", str(e))
            return []

    async def exists(self, key: str, value: Any) -> bool:
        """
        Fast indexed existence check using SELECT 1 ... LIMIT 1.
        Uses the index on url column for O(log n) lookup.
        """
        try:
            sql = f'SELECT 1 FROM {self.table_name} WHERE "{key}" = $1 LIMIT 1'
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(sql, str(value))
                return row is not None

        except Exception as e:
            log.error("PostgresStorage.exists failed: {}", str(e))
            return False

    async def clear(self) -> bool:
        """Truncates the table — removes all rows but keeps the schema."""
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                # TRUNCATE is faster than DELETE for large tables
                # RESTART IDENTITY resets the auto-increment id counter
                await conn.execute(
                    f"TRUNCATE TABLE {self.table_name} RESTART IDENTITY"
                )
            self._table_created = False
            log.debug("PostgresStorage: truncated '{}'", self.table_name)
            return True
        except Exception as e:
            log.error("PostgresStorage.clear failed: {}", str(e))
            return False

    async def count(self) -> int:
        """Returns total row count via COUNT(*)."""
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                result = await conn.fetchval(
                    f"SELECT COUNT(*) FROM {self.table_name}"
                )
                return result or 0
        except Exception:
            return 0

    async def execute(self, sql: str, *args) -> str:
        """
        Executes arbitrary SQL — for advanced queries not covered by the
        standard interface. Use with caution — no injection protection
        beyond asyncpg's parameterized query handling.

        Args:
            sql:  SQL statement with $1, $2... placeholders
            args: values for the placeholders

        Returns:
            PostgreSQL status string e.g. "INSERT 0 5"
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            return await conn.execute(sql, *args)

    async def close(self) -> None:
        """
        Closes the connection pool and releases all database connections.
        Always call this when done — otherwise connections leak.

        Usage:
            storage = PostgresStorage(...)
            try:
                await storage.save(data)
            finally:
                await storage.close()
        """
        if self._pool:
            await self._pool.close()
            self._pool = None
            log.debug("PostgresStorage: connection pool closed")

    async def __aenter__(self):
        """Enables: async with PostgresStorage(...) as storage: ..."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Automatically closes pool on exit."""
        await self.close()
        return False
