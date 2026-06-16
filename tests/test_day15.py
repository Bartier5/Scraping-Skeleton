# ── tests/test_day15.py ───────────────────────────────────────────────────────
# Day 15 — Final integration smoke tests.
# These tests verify the full skeleton is wired correctly end-to-end
# without hitting the network. They serve as a regression suite —
# run them any time you change a core module to confirm nothing broke.
#
# Run with: pytest tests/test_day15.py -v

import pytest
import asyncio
import os
import sys


# ── Project structure tests ───────────────────────────────────────────────────

class TestProjectStructure:
    """Verifies all expected modules exist and are importable."""

    def test_config_importable(self):
        from config.config import Config
        assert Config is not None

    def test_utils_importable(self):
        from utils.logger import log
        from utils.helpers import ensure_dir, hash_content, timestamp
        from utils.retry import retry
        from utils.rate_limiter import RateLimiter
        from utils.url_utils import prepare_urls, validate_urls

    def test_fetchers_importable(self):
        from fetcher.base_fetcher import BaseFetcher, FetchResult
        from fetcher.http_fetcher import HttpFetcher
        from fetcher.async_fetcher import AsyncFetcher
        from fetcher.batch_fetcher import BatchFetcher

    def test_parsers_importable(self):
        from parser.base_parser import BaseParser
        from parser.bs4_parser import BS4Parser
        from parser.lxml_parser import LxmlParser

    def test_middleware_importable(self):
        from middleware.base_middleware import BaseMiddleware, MiddlewareChain
        from middleware.retry_middleware import RetryMiddleware
        from middleware.proxy_middleware import ProxyMiddleware
        from middleware.logging_middleware import LoggingMiddleware

    def test_pipeline_importable(self):
        from pipeline.cleaner import DataCleaner
        from pipeline.transformer import DataTransformer
        from pipeline.validator import DataValidator, BookSchema

    def test_pandas_layer_importable(self):
        from pandas_layer.dataframe_builder import DataFrameBuilder
        from pandas_layer.analyzer import DataAnalyzer
        from pandas_layer.exporter import DataExporter

    def test_storage_importable(self):
        from storage.base_storage import BaseStorage, SaveResult
        from storage.csv_storage import CsvStorage
        from storage.sqlite_storage import SqliteStorage
        from storage.checkpoint_manager import CheckpointManager

    def test_anti_bot_importable(self):
        from anti_bot.proxy_manager import ProxyManager
        from anti_bot.headers_manager import HeadersManager
        from anti_bot.fingerprint_manager import FingerprintAnalyzer

    def test_scheduler_importable(self):
        from scheduler.job_scheduler import JobScheduler

    def test_spiders_importable(self):
        from spiders.base_spider import BaseSpider
        from spiders.example_spider import ExampleSpider
        from spiders.batch_spider import BatchSpider

    def test_main_importable(self):
        import main
        assert hasattr(main, "build_parser")
        assert hasattr(main, "SPIDER_REGISTRY")
        assert hasattr(main, "build_storage")

    def test_spider_registry_complete(self):
        from main import SPIDER_REGISTRY
        assert "example" in SPIDER_REGISTRY
        assert "batch" in SPIDER_REGISTRY


# ── End-to-end pipeline smoke test ───────────────────────────────────────────

class TestFullPipelineSmoke:
    """
    Full pipeline smoke test — no network, all mocked.
    Verifies every layer connects to the next correctly.
    """

    SAMPLE_HTML = """
    <!DOCTYPE html>
    <html>
    <body>
      <article class="product_pod">
        <h3><a href="../book-a_1/index.html" title="Book A">Book A</a></h3>
        <p class="price_color">£9.99</p>
        <p class="star-rating Three"></p>
        <p class="availability">In stock</p>
      </article>
      <article class="product_pod">
        <h3><a href="../book-b_2/index.html" title="Book B">Book B</a></h3>
        <p class="price_color">£14.99</p>
        <p class="star-rating Five"></p>
        <p class="availability">In stock</p>
      </article>
    </body>
    </html>
    """

    def test_parser_to_cleaner(self):
        """Parser output feeds correctly into DataCleaner."""
        from parser.bs4_parser import BS4Parser
        from pipeline.cleaner import DataCleaner

        parser = BS4Parser()
        soup = parser.make_soup(self.SAMPLE_HTML)

        titles = parser.get_all_text(soup, "h3 > a")
        prices = parser.get_all_text(soup, "p.price_color")

        raw = [{"title": t, "price_raw": p} for t, p in zip(titles, prices)]

        cleaner = DataCleaner()
        cleaned = cleaner.clean_items(raw)

        assert len(cleaned) == 2
        assert cleaned[0]["title"] == "Book A"
        assert "£" in cleaned[0]["price_raw"] or "9.99" in cleaned[0]["price_raw"]

    def test_cleaner_to_transformer(self):
        """DataCleaner output feeds correctly into DataTransformer."""
        from pipeline.cleaner import DataCleaner
        from pipeline.transformer import DataTransformer

        raw = [
            {"title": "  Book A  ", "price_raw": "£9.99",
             "url": "https://example.com/1"},
        ]

        cleaner = DataCleaner()
        transformer = DataTransformer(
            computed={
                "price": lambda item: DataCleaner.extract_number(
                    item.get("price_raw", "") or ""
                )
            },
            add_metadata=True,
        )

        cleaned = cleaner.clean_items(raw)
        transformed = transformer.transform_items(cleaned)

        assert transformed[0]["title"] == "Book A"
        assert transformed[0]["price"] == 9.99
        assert "scraped_at" in transformed[0]

    def test_transformer_to_validator(self):
        """DataTransformer output feeds correctly into DataValidator."""
        from pipeline.transformer import DataTransformer
        from pipeline.validator import DataValidator, BookSchema

        items = [
            {"title": "Book A", "price": 9.99,
             "url": "https://example.com/1", "scraped_at": "2026-01-01"},
            {"title": "Book B", "price": 14.99,
             "url": "https://example.com/2", "scraped_at": "2026-01-01"},
        ]

        validator = DataValidator(schema=BookSchema, strict=False)
        batch = validator.validate_batch(items)

        assert batch.total == 2
        assert batch.pass_rate == 1.0
        assert len(batch.valid_items) == 2

    def test_validator_to_storage(self, tmp_path):
        """DataValidator output saves correctly to SqliteStorage."""
        from pipeline.validator import DataValidator, BookSchema
        from storage.sqlite_storage import SqliteStorage

        items = [
            {"title": "Book A", "price": "9.99",
             "url": "https://example.com/1"},
        ]

        validator = DataValidator(schema=BookSchema, strict=False)
        batch = validator.validate_batch(items)

        storage = SqliteStorage(db_path=str(tmp_path / "smoke.db"))

        async def run():
            result = await storage.save(batch.valid_items)
            count = await storage.count()
            return result, count

        save_result, count = asyncio.run(run())
        assert save_result.success is True
        assert count == 1

    def test_full_pipeline_end_to_end(self, tmp_path):
        """
        Complete pipeline smoke test:
        HTML → parser → cleaner → transformer → validator → storage
        """
        from parser.bs4_parser import BS4Parser
        from pipeline.cleaner import DataCleaner
        from pipeline.transformer import DataTransformer
        from pipeline.validator import DataValidator, BookSchema
        from storage.sqlite_storage import SqliteStorage

        # ── Parse ─────────────────────────────────────────────────────────────
        parser = BS4Parser()
        soup = parser.make_soup(self.SAMPLE_HTML)

        titles  = parser.get_all_text(soup, "h3 > a")
        prices  = parser.get_all_text(soup, "p.price_color")
        ratings = parser.get_all_attr(soup, "p.star-rating", "class")
        avails  = parser.get_all_text(soup, "p.availability")
        links   = parser.get_all_attr(soup, "h3 > a", "href")

        raw_items = [
            {
                "title":        t,
                "price_raw":    p,
                "rating":       " ".join(r) if isinstance(r, list) else r,
                "availability": a,
                "url": f"https://books.toscrape.com/catalogue/{l.replace('../', '')}",
            }
            for t, p, r, a, l in zip(titles, prices, ratings, avails, links)
        ]

        assert len(raw_items) == 2

        # ── Clean ─────────────────────────────────────────────────────────────
        cleaner = DataCleaner()
        cleaned = cleaner.clean_items(raw_items)
        assert len(cleaned) == 2

        # ── Transform ─────────────────────────────────────────────────────────
        transformer = DataTransformer(
            computed={
                "price": lambda item: DataCleaner.extract_number(
                    item.get("price_raw", "") or ""
                )
            },
            add_metadata=True,
        )
        transformed = transformer.transform_items(cleaned)
        assert len(transformed) == 2
        assert isinstance(transformed[0]["price"], float)

        # ── Validate ──────────────────────────────────────────────────────────
        validator = DataValidator(schema=BookSchema, strict=False)
        batch = validator.validate_batch(transformed)
        assert batch.pass_rate == 1.0
        assert len(batch.valid_items) == 2

        # ── Store ─────────────────────────────────────────────────────────────
        storage = SqliteStorage(db_path=str(tmp_path / "e2e.db"))

        async def run():
            result = await storage.save(batch.valid_items)
            count = await storage.count()
            loaded = await storage.load()
            return result, count, loaded

        save_result, count, loaded = asyncio.run(run())
        assert save_result.success is True
        assert count == 2
        assert loaded[0]["title"] == "Book A"
        assert loaded[1]["title"] == "Book B"


# ── Checkpoint smoke test ─────────────────────────────────────────────────────

class TestCheckpointSmoke:

    def test_checkpoint_round_trip(self, tmp_path):
        from storage.checkpoint_manager import CheckpointManager
        manager = CheckpointManager(db_path=str(tmp_path / "smoke_cp.db"))

        async def run():
            await manager.init()
            urls = [f"https://example.com/{i}" for i in range(5)]

            # Mark 3 done
            for url in urls[:3]:
                await manager.mark_done(url, content_hash=f"hash_{url}")

            # get_pending should return remaining 2
            pending = await manager.get_pending(urls)
            assert len(pending) == 2

            # has_changed with same hash → False
            changed = await manager.has_changed(urls[0], f"hash_{urls[0]}")
            assert changed is False

            # has_changed with new hash → True
            changed2 = await manager.has_changed(urls[0], "completely_new_hash")
            assert changed2 is True

            stats = await manager.get_stats()
            assert stats["done"] == 3
            assert stats["total_seen"] == 3

        asyncio.run(run())


# ── Spider smoke test ─────────────────────────────────────────────────────────

class TestSpiderSmoke:

    def test_example_spider_wired(self):
        """ExampleSpider has all layers connected."""
        from spiders.example_spider import ExampleSpider
        from fetcher.async_fetcher import AsyncFetcher
        from parser.bs4_parser import BS4Parser
        from storage.sqlite_storage import SqliteStorage

        spider = ExampleSpider(concurrency=5)
        assert isinstance(spider.fetcher, AsyncFetcher)
        assert isinstance(spider.parser, BS4Parser)
        assert isinstance(spider.storage, SqliteStorage)

    def test_batch_spider_wired(self):
        """BatchSpider has all layers connected."""
        from spiders.batch_spider import BatchSpider
        from fetcher.async_fetcher import AsyncFetcher
        from parser.bs4_parser import BS4Parser
        from storage.sqlite_storage import SqliteStorage

        spider = BatchSpider(concurrency=5)
        assert isinstance(spider.fetcher, AsyncFetcher)
        assert isinstance(spider.parser, BS4Parser)
        assert isinstance(spider.storage, SqliteStorage)

    def test_example_spider_runs_mocked(self):
        """ExampleSpider.run() completes and returns valid stats."""
        from spiders.example_spider import ExampleSpider
        from storage.base_storage import SaveResult
        from fetcher.base_fetcher import FetchResult
        from unittest.mock import patch, AsyncMock

        HTML = """<html><body>
        <article class="product_pod">
          <h3><a href="../book_1/index.html">Book A</a></h3>
          <p class="price_color">£9.99</p>
          <p class="star-rating Three"></p>
          <p class="availability">In stock</p>
        </article></body></html>"""

        spider = ExampleSpider(concurrency=2)

        async def mock_fetch(url, **kwargs):
            return FetchResult(url=url, status_code=200, html=HTML)

        async def mock_save(items, **kwargs):
            return SaveResult(success=True, rows_saved=len(items), backend="test")

        async def run():
            with patch.object(spider.fetcher, "async_fetch", side_effect=mock_fetch):
                with patch.object(spider.storage, "save", side_effect=mock_save):
                    return await spider.run(urls=["https://books.toscrape.com/page-1.html"])

        stats = asyncio.run(run())

        assert stats["spider"] == "ExampleSpider"
        assert stats["urls_fetched"] == 1
        assert stats["urls_failed"] == 0
        assert stats["items_saved"] > 0
        assert stats["started_at"] is not None
        assert stats["finished_at"] is not None


# ── Config smoke test ─────────────────────────────────────────────────────────

class TestConfigSmoke:

    def test_config_has_required_fields(self):
        from config.config import Config
        assert hasattr(Config, "CONCURRENCY")
        assert hasattr(Config, "TIMEOUT")
        assert hasattr(Config, "STORAGE_BACKEND")
        assert hasattr(Config, "OUTPUT_DIR")
        assert hasattr(Config, "LOG_LEVEL")

    def test_concurrency_is_positive_int(self):
        from config.config import Config
        assert isinstance(Config.CONCURRENCY, int)
        assert Config.CONCURRENCY > 0

    def test_output_dir_string(self):
        from config.config import Config
        assert isinstance(Config.OUTPUT_DIR, str)
        assert len(Config.OUTPUT_DIR) > 0
