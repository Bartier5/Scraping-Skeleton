# ── tests/test_day11.py ───────────────────────────────────────────────────────
# Tests for Day 11: PostgresStorage
#
# Because PostgresStorage requires a live PostgreSQL instance, most tests
# use mocking to simulate asyncpg responses. This lets the test suite run
# without any database setup while still verifying all logic paths.
#
# Integration tests (marked with @pytest.mark.integration) require a real
# PostgreSQL instance and are skipped by default.
# To run integration tests:
#   POSTGRES_URL=postgresql://user:pass@localhost:5432/scraper_db pytest tests/test_day11.py -m integration -v
#
# Run unit tests only (default):
#   pytest tests/test_day11.py -v

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


SAMPLE_DATA = [
    {"title": "Book A", "price": "9.99",  "url": "https://example.com/1"},
    {"title": "Book B", "price": "14.99", "url": "https://example.com/2"},
    {"title": "Book C", "price": "7.49",  "url": "https://example.com/3"},
]


# ── Unit Tests (no real DB needed) ────────────────────────────────────────────

class TestPostgresStorageInit:

    def test_initializes_with_dsn(self):
        from storage.postgres_storage import PostgresStorage
        storage = PostgresStorage(dsn="postgresql://user:pass@localhost/db")
        assert storage.dsn == "postgresql://user:pass@localhost/db"
        assert storage.table_name == "scraped_data"
        assert storage._pool is None

    def test_initializes_with_custom_table(self):
        from storage.postgres_storage import PostgresStorage
        storage = PostgresStorage(dsn="postgresql://x/db", table_name="books")
        assert storage.table_name == "books"

    def test_initializes_with_upsert_on(self):
        from storage.postgres_storage import PostgresStorage
        storage = PostgresStorage(dsn="postgresql://x/db", upsert_on="url")
        assert storage.upsert_on == "url"

    def test_pool_size_stored(self):
        from storage.postgres_storage import PostgresStorage
        storage = PostgresStorage(dsn="postgresql://x/db", pool_size=10)
        assert storage.pool_size == 10

    def test_table_not_created_initially(self):
        from storage.postgres_storage import PostgresStorage
        storage = PostgresStorage(dsn="postgresql://x/db")
        assert storage._table_created is False

    def test_raises_if_no_dsn(self):
        from storage.postgres_storage import PostgresStorage
        import os
        # Temporarily clear POSTGRES_URL from environment
        original = os.environ.pop("POSTGRES_URL", None)
        try:
            storage = PostgresStorage(dsn="")
            storage.dsn = ""   # force empty

            async def run():
                return await storage._get_pool()

            with pytest.raises((RuntimeError, Exception)):
                asyncio.run(run())
        finally:
            if original:
                os.environ["POSTGRES_URL"] = original


class TestPostgresStorageWithMocks:
    """Tests that mock asyncpg so no real DB is needed."""

    def _make_mock_pool(self):
        """Builds a mock asyncpg pool that supports async with syntax."""
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="INSERT 0 3")
        mock_conn.executemany = AsyncMock(return_value=None)
        mock_conn.fetch = AsyncMock(return_value=[
            {"id": 1, "title": "Book A", "price": "9.99", "url": "https://example.com/1"},
        ])
        mock_conn.fetchrow = AsyncMock(return_value={"exists": 1})
        mock_conn.fetchval = AsyncMock(return_value=3)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        mock_pool = AsyncMock()
        mock_pool.acquire = MagicMock(return_value=mock_conn)
        mock_pool.close = AsyncMock()

        return mock_pool, mock_conn

    def test_save_returns_save_result(self):
        from storage.postgres_storage import PostgresStorage
        from storage.base_storage import SaveResult

        storage = PostgresStorage(dsn="postgresql://x/db")
        mock_pool, mock_conn = self._make_mock_pool()
        storage._pool = mock_pool
        storage._table_created = True

        async def run():
            return await storage.save(SAMPLE_DATA)

        result = asyncio.run(run())
        assert isinstance(result, SaveResult)
        assert result.success is True
        assert result.rows_saved == 3
        assert result.backend == "postgres"

    def test_save_empty_returns_success(self):
        from storage.postgres_storage import PostgresStorage

        storage = PostgresStorage(dsn="postgresql://x/db")

        async def run():
            return await storage.save([])

        result = asyncio.run(run())
        assert result.success is True
        assert result.rows_saved == 0

    def test_load_returns_list(self):
        from storage.postgres_storage import PostgresStorage

        storage = PostgresStorage(dsn="postgresql://x/db")
        mock_pool, mock_conn = self._make_mock_pool()
        storage._pool = mock_pool
        storage._table_created = True

        async def run():
            return await storage.load()

        result = asyncio.run(run())
        assert isinstance(result, list)

    def test_exists_true(self):
        from storage.postgres_storage import PostgresStorage

        storage = PostgresStorage(dsn="postgresql://x/db")
        mock_pool, mock_conn = self._make_mock_pool()
        storage._pool = mock_pool
        storage._table_created = True

        async def run():
            return await storage.exists("url", "https://example.com/1")

        result = asyncio.run(run())
        assert result is True

    def test_exists_false(self):
        from storage.postgres_storage import PostgresStorage

        storage = PostgresStorage(dsn="postgresql://x/db")
        mock_pool, mock_conn = self._make_mock_pool()
        mock_conn.fetchrow = AsyncMock(return_value=None)   # nothing found
        storage._pool = mock_pool
        storage._table_created = True

        async def run():
            return await storage.exists("url", "https://not-found.com")

        result = asyncio.run(run())
        assert result is False

    def test_count_returns_int(self):
        from storage.postgres_storage import PostgresStorage

        storage = PostgresStorage(dsn="postgresql://x/db")
        mock_pool, mock_conn = self._make_mock_pool()
        storage._pool = mock_pool
        storage._table_created = True

        async def run():
            return await storage.count()

        result = asyncio.run(run())
        assert isinstance(result, int)
        assert result == 3

    def test_clear_returns_true(self):
        from storage.postgres_storage import PostgresStorage

        storage = PostgresStorage(dsn="postgresql://x/db")
        mock_pool, mock_conn = self._make_mock_pool()
        storage._pool = mock_pool
        storage._table_created = True

        async def run():
            return await storage.clear()

        result = asyncio.run(run())
        assert result is True

    def test_close_clears_pool(self):
        from storage.postgres_storage import PostgresStorage

        storage = PostgresStorage(dsn="postgresql://x/db")
        mock_pool, _ = self._make_mock_pool()
        storage._pool = mock_pool

        async def run():
            await storage.close()

        asyncio.run(run())
        assert storage._pool is None

    def test_upsert_mode_uses_on_conflict(self):
        """Verifies upsert SQL is built correctly when upsert_on is set."""
        from storage.postgres_storage import PostgresStorage

        storage = PostgresStorage(dsn="postgresql://x/db", upsert_on="url")
        mock_pool, mock_conn = self._make_mock_pool()
        storage._pool = mock_pool
        storage._table_created = True

        executed_sql = []

        async def capture_executemany(sql, rows):
            executed_sql.append(sql)

        mock_conn.executemany = capture_executemany

        async def run():
            await storage.save(SAMPLE_DATA)

        asyncio.run(run())

        # Verify ON CONFLICT clause was included in the SQL
        assert len(executed_sql) > 0
        assert "ON CONFLICT" in executed_sql[0]

    def test_save_without_upsert_uses_plain_insert(self):
        """Verifies plain INSERT is used when upsert_on is not set."""
        from storage.postgres_storage import PostgresStorage

        storage = PostgresStorage(dsn="postgresql://x/db", upsert_on=None)
        mock_pool, mock_conn = self._make_mock_pool()
        storage._pool = mock_pool
        storage._table_created = True

        executed_sql = []

        async def capture_executemany(sql, rows):
            executed_sql.append(sql)

        mock_conn.executemany = capture_executemany

        async def run():
            await storage.save(SAMPLE_DATA)

        asyncio.run(run())

        assert len(executed_sql) > 0
        assert "ON CONFLICT" not in executed_sql[0]

    def test_context_manager_closes_pool(self):
        """Verifies async with closes the pool on exit."""
        from storage.postgres_storage import PostgresStorage

        storage = PostgresStorage(dsn="postgresql://x/db")
        mock_pool, _ = self._make_mock_pool()
        storage._pool = mock_pool

        async def run():
            async with storage:
                pass   # just enter and exit
            # Pool should be None after exit

        asyncio.run(run())
        assert storage._pool is None

    def test_save_result_metadata_contains_table(self):
        from storage.postgres_storage import PostgresStorage

        storage = PostgresStorage(dsn="postgresql://x/db", table_name="my_books")
        mock_pool, mock_conn = self._make_mock_pool()
        storage._pool = mock_pool
        storage._table_created = True

        async def run():
            return await storage.save(SAMPLE_DATA)

        result = asyncio.run(run())
        assert result.metadata.get("table") == "my_books"

    def test_load_with_limit(self):
        from storage.postgres_storage import PostgresStorage

        storage = PostgresStorage(dsn="postgresql://x/db")
        mock_pool, mock_conn = self._make_mock_pool()
        storage._pool = mock_pool
        storage._table_created = True

        captured_sql = []

        async def capture_fetch(sql, *args):
            captured_sql.append(sql)
            return []

        mock_conn.fetch = capture_fetch

        async def run():
            return await storage.load(limit=5)

        asyncio.run(run())
        assert any("LIMIT 5" in sql for sql in captured_sql)

    def test_load_with_where_clause(self):
        from storage.postgres_storage import PostgresStorage

        storage = PostgresStorage(dsn="postgresql://x/db")
        mock_pool, mock_conn = self._make_mock_pool()
        storage._pool = mock_pool
        storage._table_created = True

        captured_sql = []

        async def capture_fetch(sql, *args):
            captured_sql.append(sql)
            return []

        mock_conn.fetch = capture_fetch

        async def run():
            return await storage.load(where="price > '10'")

        asyncio.run(run())
        assert any("WHERE price > '10'" in sql for sql in captured_sql)


# ── Integration Tests (require real PostgreSQL) ───────────────────────────────

@pytest.mark.integration
class TestPostgresStorageIntegration:
    """
    These tests require a real PostgreSQL instance.
    Set POSTGRES_URL in your environment before running.

    Run with:
        pytest tests/test_day11.py -m integration -v
    """

    @pytest.fixture
    def storage(self):
        from storage.postgres_storage import PostgresStorage
        import os
        dsn = os.environ.get("POSTGRES_URL", Config.POSTGRES_URL)
        return PostgresStorage(
            dsn=dsn,
            table_name="test_books",
            upsert_on="url",
        )

    @pytest.mark.integration
    def test_full_save_load_cycle(self, storage):
        async def run():
            await storage.clear()
            save_result = await storage.save(SAMPLE_DATA)
            assert save_result.success is True
            assert save_result.rows_saved == 3

            count = await storage.count()
            assert count == 3

            rows = await storage.load()
            assert len(rows) == 3

            await storage.close()

        asyncio.run(run())

    @pytest.mark.integration
    def test_upsert_prevents_duplicates(self, storage):
        async def run():
            await storage.clear()
            await storage.save(SAMPLE_DATA)
            await storage.save(SAMPLE_DATA)   # save same data again

            count = await storage.count()
            assert count == 3   # upsert — no duplicates

            await storage.close()

        asyncio.run(run())
