# ── tests/test_day13.py ───────────────────────────────────────────────────────
# Tests for Day 13: JobScheduler and main.py CLI
# Run with: pytest tests/test_day13.py -v

import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock


# ── JobScheduler Tests ────────────────────────────────────────────────────────

class TestJobScheduler:

    def test_initializes(self):
        from scheduler.job_scheduler import JobScheduler
        scheduler = JobScheduler()
        assert scheduler.is_running is False
        assert scheduler._running is False

    def test_start_and_stop(self):
        from scheduler.job_scheduler import JobScheduler
        scheduler = JobScheduler()

        async def run():
            await scheduler.start()
            assert scheduler.is_running is True
            await scheduler.stop()
            assert scheduler.is_running is False

        asyncio.run(run())

    def test_double_start_safe(self):
        from scheduler.job_scheduler import JobScheduler
        scheduler = JobScheduler()

        async def run():
            await scheduler.start()
            await scheduler.start()   # should not raise
            assert scheduler.is_running is True
            await scheduler.stop()

        asyncio.run(run())

    def test_run_once_adds_job(self):
        from scheduler.job_scheduler import JobScheduler
        scheduler = JobScheduler()

        async def run():
            await scheduler.start()
            job = scheduler.run_once(
                lambda: None,
                job_id="test_once",
                delay_seconds=9999,   # far future — won't actually fire
            )
            assert job is not None
            jobs = scheduler.get_jobs()
            assert any(j["id"] == "test_once" for j in jobs)
            await scheduler.stop()

        asyncio.run(run())

    def test_run_interval_adds_job(self):
        from scheduler.job_scheduler import JobScheduler
        scheduler = JobScheduler()

        async def run():
            await scheduler.start()
            job = scheduler.run_interval(
                lambda: None,
                job_id="test_interval",
                hours=1,
                start_immediately=False,
            )
            assert job is not None
            jobs = scheduler.get_jobs()
            assert any(j["id"] == "test_interval" for j in jobs)
            await scheduler.stop()

        asyncio.run(run())

    def test_run_cron_adds_job(self):
        from scheduler.job_scheduler import JobScheduler
        scheduler = JobScheduler()

        async def run():
            await scheduler.start()
            job = scheduler.run_cron(
                lambda: None,
                job_id="test_cron",
                hour="9",
                minute="0",
            )
            assert job is not None
            jobs = scheduler.get_jobs()
            assert any(j["id"] == "test_cron" for j in jobs)
            await scheduler.stop()

        asyncio.run(run())

    def test_remove_job(self):
        from scheduler.job_scheduler import JobScheduler
        scheduler = JobScheduler()

        async def run():
            await scheduler.start()
            scheduler.run_once(lambda: None, job_id="to_remove", delay_seconds=9999)
            removed = scheduler.remove_job("to_remove")
            assert removed is True
            jobs = scheduler.get_jobs()
            assert not any(j["id"] == "to_remove" for j in jobs)
            await scheduler.stop()

        asyncio.run(run())

    def test_remove_nonexistent_job(self):
        from scheduler.job_scheduler import JobScheduler
        scheduler = JobScheduler()

        async def run():
            await scheduler.start()
            result = scheduler.remove_job("nonexistent_job")
            assert result is False
            await scheduler.stop()

        asyncio.run(run())

    def test_pause_and_resume_job(self):
        from scheduler.job_scheduler import JobScheduler
        scheduler = JobScheduler()

        async def run():
            await scheduler.start()
            scheduler.run_interval(
                lambda: None,
                job_id="pausable",
                minutes=30,
                start_immediately=False,
            )
            paused = scheduler.pause_job("pausable")
            assert paused is True

            resumed = scheduler.resume_job("pausable")
            assert resumed is True
            await scheduler.stop()

        asyncio.run(run())

    def test_job_executes_and_history_recorded(self):
        from scheduler.job_scheduler import JobScheduler
        scheduler = JobScheduler()
        executed = {"count": 0}

        async def test_job():
            executed["count"] += 1

        async def run():
            await scheduler.start()
            # Run immediately — delay_seconds=0
            scheduler.run_once(test_job, job_id="immediate", delay_seconds=0)
            # Wait for job to execute
            await asyncio.sleep(0.5)
            await scheduler.stop()

        asyncio.run(run())

        assert executed["count"] == 1
        history = scheduler.get_job_history()
        assert len(history) >= 1
        assert history[0]["job_id"] == "immediate"
        assert history[0]["status"] == "success"

    def test_job_error_recorded_in_history(self):
        from scheduler.job_scheduler import JobScheduler
        scheduler = JobScheduler()

        async def failing_job():
            raise ValueError("Simulated job failure")

        async def run():
            await scheduler.start()
            scheduler.run_once(failing_job, job_id="will_fail", delay_seconds=0)
            await asyncio.sleep(0.5)
            await scheduler.stop()

        asyncio.run(run())

        history = scheduler.get_job_history()
        failed = [h for h in history if h["status"] == "error"]
        assert len(failed) >= 1
        assert "Simulated job failure" in failed[0]["error"]

    def test_replace_existing_job(self):
        from scheduler.job_scheduler import JobScheduler
        scheduler = JobScheduler()

        async def run():
            await scheduler.start()
            scheduler.run_interval(lambda: None, job_id="replaceable", hours=1,
                                   start_immediately=False)
            # Add same job_id again — should replace without error
            scheduler.run_interval(lambda: None, job_id="replaceable", hours=2,
                                   start_immediately=False)
            jobs = scheduler.get_jobs()
            replaceable = [j for j in jobs if j["id"] == "replaceable"]
            assert len(replaceable) == 1   # only one, not two
            await scheduler.stop()

        asyncio.run(run())

    def test_get_jobs_returns_list(self):
        from scheduler.job_scheduler import JobScheduler
        scheduler = JobScheduler()

        async def run():
            await scheduler.start()
            scheduler.run_once(lambda: None, job_id="j1", delay_seconds=9999)
            scheduler.run_once(lambda: None, job_id="j2", delay_seconds=9999)
            jobs = scheduler.get_jobs()
            assert isinstance(jobs, list)
            assert len(jobs) == 2
            assert all("id" in j and "next_run" in j for j in jobs)
            await scheduler.stop()

        asyncio.run(run())

    def test_repr(self):
        from scheduler.job_scheduler import JobScheduler
        scheduler = JobScheduler()
        r = repr(scheduler)
        assert "JobScheduler" in r
        assert "running=False" in r


# ── CLI / main.py Tests ───────────────────────────────────────────────────────

class TestCLI:

    def test_build_parser_returns_parser(self):
        from main import build_parser
        parser = build_parser()
        assert parser is not None

    def test_default_spider_is_example(self):
        from main import build_parser
        parser = build_parser()
        args = parser.parse_args([])
        assert args.spider == "example"

    def test_default_mode_is_single(self):
        from main import build_parser
        parser = build_parser()
        args = parser.parse_args([])
        assert args.mode == "single"

    def test_spider_flag(self):
        from main import build_parser
        parser = build_parser()
        args = parser.parse_args(["--spider", "batch"])
        assert args.spider == "batch"

    def test_mode_flag(self):
        from main import build_parser
        parser = build_parser()
        args = parser.parse_args(["--mode", "batch"])
        assert args.mode == "batch"

    def test_concurrency_flag(self):
        from main import build_parser
        parser = build_parser()
        args = parser.parse_args(["--concurrency", "20"])
        assert args.concurrency == 20

    def test_storage_flag(self):
        from main import build_parser
        parser = build_parser()
        args = parser.parse_args(["--storage", "sqlite"])
        assert args.storage == "sqlite"

    def test_url_flag(self):
        from main import build_parser
        parser = build_parser()
        args = parser.parse_args(["--url", "https://example.com"])
        assert args.url == "https://example.com"

    def test_dry_run_flag(self):
        from main import build_parser
        parser = build_parser()
        args = parser.parse_args(["--dry-run"])
        assert args.dry_run is True

    def test_interval_flag(self):
        from main import build_parser
        parser = build_parser()
        args = parser.parse_args(["--interval", "3600"])
        assert args.interval == 3600

    def test_cron_flag(self):
        from main import build_parser
        parser = build_parser()
        args = parser.parse_args(["--cron", "0 9 * * *"])
        assert args.cron == "0 9 * * *"

    def test_invalid_mode_rejected(self):
        from main import build_parser
        import sys
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--mode", "invalid_mode"])

    def test_invalid_storage_rejected(self):
        from main import build_parser
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--storage", "redis"])

    def test_list_spiders_output(self, capsys):
        from main import list_spiders
        list_spiders()
        captured = capsys.readouterr()
        assert "example" in captured.out
        assert "batch" in captured.out

    def test_load_spider_unknown_exits(self):
        from main import load_spider
        with pytest.raises(SystemExit):
            load_spider("nonexistent_spider")

    def test_spider_registry_has_expected_spiders(self):
        from main import SPIDER_REGISTRY
        assert "example" in SPIDER_REGISTRY
        assert "batch" in SPIDER_REGISTRY

    def test_dry_run_does_not_call_spider(self):
        from main import main_async, build_parser

        parser = build_parser()
        args = parser.parse_args([
            "--dry-run",
            "--spider", "example",
            "--url", "https://example.com",
        ])

        # dry_run should complete without loading or calling any spider
        asyncio.run(main_async(args))
        # If we get here without error, dry run worked correctly

    def test_build_storage_csv(self, tmp_path):
        from main import build_storage
        storage = build_storage("csv", str(tmp_path))
        from storage.csv_storage import CsvStorage
        assert isinstance(storage, CsvStorage)

    def test_build_storage_sqlite(self, tmp_path):
        from main import build_storage
        storage = build_storage("sqlite", str(tmp_path))
        from storage.sqlite_storage import SqliteStorage
        assert isinstance(storage, SqliteStorage)
