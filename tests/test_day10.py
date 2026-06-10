# ── tests/test_day10.py ───────────────────────────────────────────────────────
# Isolation tests for Day 10: CsvStorage, SqliteStorage, CheckpointManager
# Run with: pytest tests/test_day10.py -v

import pytest
import asyncio
import os
import csv


SAMPLE_DATA = [
    {"title": "Book A", "price": "9.99",  "url": "https://example.com/1"},
    {"title": "Book B", "price": "14.99", "url": "https://example.com/2"},
    {"title": "Book C", "price": "7.49",  "url": "https://example.com/3"},
]


# ── CsvStorage Tests ──────────────────────────────────────────────────────────

class TestCsvStorage:

    def test_save_creates_file(self, tmp_path):
        from storage.csv_storage import CsvStorage
        filepath = str(tmp_path / "test.csv")
        storage = CsvStorage(filepath=filepath)

        async def run():
            return await storage.save(SAMPLE_DATA)

        result = asyncio.run(run())
        assert result.success is True
        assert os.path.exists(filepath)

    def test_save_correct_row_count(self, tmp_path):
        from storage.csv_storage import CsvStorage
        filepath = str(tmp_path / "test.csv")
        storage = CsvStorage(filepath=filepath)

        async def run():
            await storage.save(SAMPLE_DATA)
            return await storage.count()

        count = asyncio.run(run())
        assert count == 3

    def test_save_empty_returns_success(self, tmp_path):
        from storage.csv_storage import CsvStorage
        storage = CsvStorage(filepath=str(tmp_path / "test.csv"))

        async def run():
            return await storage.save([])

        result = asyncio.run(run())
        assert result.success is True
        assert result.rows_saved == 0

    def test_append_mode_adds_rows(self, tmp_path):
        from storage.csv_storage import CsvStorage
        filepath = str(tmp_path / "test.csv")
        storage = CsvStorage(filepath=filepath, mode="append")

        async def run():
            await storage.save(SAMPLE_DATA[:2])
            await storage.save(SAMPLE_DATA[2:])
            return await storage.count()

        count = asyncio.run(run())
        assert count == 3

    def test_overwrite_mode_replaces_rows(self, tmp_path):
        from storage.csv_storage import CsvStorage
        filepath = str(tmp_path / "test.csv")
        storage = CsvStorage(filepath=filepath, mode="overwrite")

        async def run():
            await storage.save(SAMPLE_DATA)
            await storage.save(SAMPLE_DATA[:1])   # overwrite with 1 row
            return await storage.count()

        count = asyncio.run(run())
        assert count == 1

    def test_load_returns_list_of_dicts(self, tmp_path):
        from storage.csv_storage import CsvStorage
        filepath = str(tmp_path / "test.csv")
        storage = CsvStorage(filepath=filepath)

        async def run():
            await storage.save(SAMPLE_DATA)
            return await storage.load()

        rows = asyncio.run(run())
        assert isinstance(rows, list)
        assert len(rows) == 3
        assert isinstance(rows[0], dict)

    def test_load_with_limit(self, tmp_path):
        from storage.csv_storage import CsvStorage
        storage = CsvStorage(filepath=str(tmp_path / "test.csv"))

        async def run():
            await storage.save(SAMPLE_DATA)
            return await storage.load(limit=2)

        rows = asyncio.run(run())
        assert len(rows) == 2

    def test_load_nonexistent_file(self, tmp_path):
        from storage.csv_storage import CsvStorage
        storage = CsvStorage(filepath=str(tmp_path / "missing.csv"))

        async def run():
            return await storage.load()

        rows = asyncio.run(run())
        assert rows == []

    def test_exists_true(self, tmp_path):
        from storage.csv_storage import CsvStorage
        storage = CsvStorage(filepath=str(tmp_path / "test.csv"))

        async def run():
            await storage.save(SAMPLE_DATA)
            return await storage.exists("url", "https://example.com/1")

        assert asyncio.run(run()) is True

    def test_exists_false(self, tmp_path):
        from storage.csv_storage import CsvStorage
        storage = CsvStorage(filepath=str(tmp_path / "test.csv"))

        async def run():
            await storage.save(SAMPLE_DATA)
            return await storage.exists("url", "https://not-saved.com")

        assert asyncio.run(run()) is False

    def test_clear_removes_file(self, tmp_path):
        from storage.csv_storage import CsvStorage
        filepath = str(tmp_path / "test.csv")
        storage = CsvStorage(filepath=filepath)

        async def run():
            await storage.save(SAMPLE_DATA)
            await storage.clear()

        asyncio.run(run())
        assert not os.path.exists(filepath)

    def test_count_zero_when_no_file(self, tmp_path):
        from storage.csv_storage import CsvStorage
        storage = CsvStorage(filepath=str(tmp_path / "missing.csv"))

        async def run():
            return await storage.count()

        assert asyncio.run(run()) == 0

    def test_save_result_backend_is_csv(self, tmp_path):
        from storage.csv_storage import CsvStorage
        storage = CsvStorage(filepath=str(tmp_path / "test.csv"))

        async def run():
            return await storage.save(SAMPLE_DATA)

        result = asyncio.run(run())
        assert result.backend == "csv"


# ── SqliteStorage Tests ───────────────────────────────────────────────────────

class TestSqliteStorage:

    def test_save_returns_save_result(self, tmp_path):
        from storage.sqlite_storage import SqliteStorage
        from storage.base_storage import SaveResult
        storage = SqliteStorage(db_path=str(tmp_path / "test.db"))

        async def run():
            return await storage.save(SAMPLE_DATA)

        result = asyncio.run(run())
        assert isinstance(result, SaveResult)
        assert result.success is True

    def test_save_correct_row_count(self, tmp_path):
        from storage.sqlite_storage import SqliteStorage
        storage = SqliteStorage(db_path=str(tmp_path / "test.db"))

        async def run():
            await storage.save(SAMPLE_DATA)
            return await storage.count()

        count = asyncio.run(run())
        assert count == 3

    def test_save_empty_returns_success(self, tmp_path):
        from storage.sqlite_storage import SqliteStorage
        storage = SqliteStorage(db_path=str(tmp_path / "test.db"))

        async def run():
            return await storage.save([])

        result = asyncio.run(run())
        assert result.success is True
        assert result.rows_saved == 0

    def test_multiple_saves_accumulate(self, tmp_path):
        from storage.sqlite_storage import SqliteStorage
        storage = SqliteStorage(db_path=str(tmp_path / "test.db"))

        async def run():
            await storage.save(SAMPLE_DATA[:2])
            await storage.save(SAMPLE_DATA[2:])
            return await storage.count()

        count = asyncio.run(run())
        assert count == 3

    def test_load_returns_list(self, tmp_path):
        from storage.sqlite_storage import SqliteStorage
        storage = SqliteStorage(db_path=str(tmp_path / "test.db"))

        async def run():
            await storage.save(SAMPLE_DATA)
            return await storage.load()

        rows = asyncio.run(run())
        assert isinstance(rows, list)
        assert len(rows) == 3

    def test_load_with_limit(self, tmp_path):
        from storage.sqlite_storage import SqliteStorage
        storage = SqliteStorage(db_path=str(tmp_path / "test.db"))

        async def run():
            await storage.save(SAMPLE_DATA)
            return await storage.load(limit=2)

        rows = asyncio.run(run())
        assert len(rows) == 2

    def test_exists_true(self, tmp_path):
        from storage.sqlite_storage import SqliteStorage
        storage = SqliteStorage(db_path=str(tmp_path / "test.db"))

        async def run():
            await storage.save(SAMPLE_DATA)
            return await storage.exists("url", "https://example.com/1")

        assert asyncio.run(run()) is True

    def test_exists_false(self, tmp_path):
        from storage.sqlite_storage import SqliteStorage
        storage = SqliteStorage(db_path=str(tmp_path / "test.db"))

        async def run():
            await storage.save(SAMPLE_DATA)
            return await storage.exists("url", "https://not-saved.com")

        assert asyncio.run(run()) is False

    def test_clear_removes_rows(self, tmp_path):
        from storage.sqlite_storage import SqliteStorage
        storage = SqliteStorage(db_path=str(tmp_path / "test.db"))

        async def run():
            await storage.save(SAMPLE_DATA)
            await storage.clear()
            return await storage.count()

        count = asyncio.run(run())
        assert count == 0

    def test_count_zero_initially(self, tmp_path):
        from storage.sqlite_storage import SqliteStorage
        storage = SqliteStorage(db_path=str(tmp_path / "test.db"))

        async def run():
            await storage.save([])   # init table
            return await storage.count()

        assert asyncio.run(run()) == 0

    def test_checkpoint_and_is_checkpointed(self, tmp_path):
        from storage.sqlite_storage import SqliteStorage
        storage = SqliteStorage(db_path=str(tmp_path / "test.db"))

        async def run():
            await storage.checkpoint("https://example.com/1")
            return await storage.is_checkpointed("https://example.com/1")

        assert asyncio.run(run()) is True

    def test_not_checkpointed_initially(self, tmp_path):
        from storage.sqlite_storage import SqliteStorage
        storage = SqliteStorage(db_path=str(tmp_path / "test.db"))

        async def run():
            return await storage.is_checkpointed("https://never-seen.com")

        assert asyncio.run(run()) is False

    def test_clear_checkpoints(self, tmp_path):
        from storage.sqlite_storage import SqliteStorage
        storage = SqliteStorage(db_path=str(tmp_path / "test.db"))

        async def run():
            await storage.checkpoint("https://example.com/1")
            await storage.clear_checkpoints()
            return await storage.is_checkpointed("https://example.com/1")

        assert asyncio.run(run()) is False

    def test_save_result_backend_is_sqlite(self, tmp_path):
        from storage.sqlite_storage import SqliteStorage
        storage = SqliteStorage(db_path=str(tmp_path / "test.db"))

        async def run():
            return await storage.save(SAMPLE_DATA)

        result = asyncio.run(run())
        assert result.backend == "sqlite"


# ── CheckpointManager Tests ───────────────────────────────────────────────────

class TestCheckpointManager:

    def test_mark_done_and_is_done(self, tmp_path):
        from storage.checkpoint_manager import CheckpointManager
        manager = CheckpointManager(db_path=str(tmp_path / "cp.db"))

        async def run():
            await manager.init()
            await manager.mark_done("https://example.com/1")
            return await manager.is_done("https://example.com/1")

        assert asyncio.run(run()) is True

    def test_not_done_initially(self, tmp_path):
        from storage.checkpoint_manager import CheckpointManager
        manager = CheckpointManager(db_path=str(tmp_path / "cp.db"))

        async def run():
            await manager.init()
            return await manager.is_done("https://never-seen.com")

        assert asyncio.run(run()) is False

    def test_mark_failed_not_done(self, tmp_path):
        from storage.checkpoint_manager import CheckpointManager
        manager = CheckpointManager(db_path=str(tmp_path / "cp.db"))

        async def run():
            await manager.init()
            await manager.mark_failed("https://example.com/1", reason="timeout")
            return await manager.is_done("https://example.com/1")

        # Failed URLs are NOT considered done — they can be retried
        assert asyncio.run(run()) is False

    def test_get_pending_filters_done_urls(self, tmp_path):
        from storage.checkpoint_manager import CheckpointManager
        manager = CheckpointManager(db_path=str(tmp_path / "cp.db"))
        all_urls = [f"https://example.com/{i}" for i in range(5)]

        async def run():
            await manager.init()
            # Mark first 3 as done
            for url in all_urls[:3]:
                await manager.mark_done(url)
            # get_pending should return only the remaining 2
            return await manager.get_pending(all_urls)

        pending = asyncio.run(run())
        assert len(pending) == 2
        assert "https://example.com/0" not in pending
        assert "https://example.com/3" in pending
        assert "https://example.com/4" in pending

    def test_has_changed_new_url_returns_true(self, tmp_path):
        from storage.checkpoint_manager import CheckpointManager
        manager = CheckpointManager(db_path=str(tmp_path / "cp.db"))

        async def run():
            await manager.init()
            # URL never seen before → has_changed should return True
            return await manager.has_changed("https://example.com/new", "abc123")

        assert asyncio.run(run()) is True

    def test_has_changed_same_hash_returns_false(self, tmp_path):
        from storage.checkpoint_manager import CheckpointManager
        manager = CheckpointManager(db_path=str(tmp_path / "cp.db"))

        async def run():
            await manager.init()
            await manager.mark_done("https://example.com/1", content_hash="abc123")
            return await manager.has_changed("https://example.com/1", "abc123")

        # Same hash → content unchanged → has_changed is False
        assert asyncio.run(run()) is False

    def test_has_changed_different_hash_returns_true(self, tmp_path):
        from storage.checkpoint_manager import CheckpointManager
        manager = CheckpointManager(db_path=str(tmp_path / "cp.db"))

        async def run():
            await manager.init()
            await manager.mark_done("https://example.com/1", content_hash="old_hash")
            return await manager.has_changed("https://example.com/1", "new_hash")

        # Different hash → content changed → has_changed is True
        assert asyncio.run(run()) is True

    def test_get_stats(self, tmp_path):
        from storage.checkpoint_manager import CheckpointManager
        manager = CheckpointManager(db_path=str(tmp_path / "cp.db"))

        async def run():
            await manager.init()
            await manager.mark_done("https://example.com/1")
            await manager.mark_done("https://example.com/2")
            await manager.mark_failed("https://example.com/3", "timeout")
            return await manager.get_stats()

        stats = asyncio.run(run())
        assert stats["done"] == 2
        assert stats["failed"] == 1
        assert stats["total_seen"] == 3

    def test_reset_clears_all(self, tmp_path):
        from storage.checkpoint_manager import CheckpointManager
        manager = CheckpointManager(db_path=str(tmp_path / "cp.db"))

        async def run():
            await manager.init()
            await manager.mark_done("https://example.com/1")
            await manager.mark_done("https://example.com/2")
            await manager.reset()
            return await manager.get_stats()

        stats = asyncio.run(run())
        assert stats["total_seen"] == 0

    def test_get_pending_empty_input(self, tmp_path):
        from storage.checkpoint_manager import CheckpointManager
        manager = CheckpointManager(db_path=str(tmp_path / "cp.db"))

        async def run():
            await manager.init()
            return await manager.get_pending([])

        assert asyncio.run(run()) == []
