# ── tests/test_day14.py ───────────────────────────────────────────────────────
# Tests for Day 14: BaseSpider, ExampleSpider, BatchSpider
# All HTTP calls are mocked — no network needed.
# Run with: pytest tests/test_day14.py -v

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


# ── Shared helpers ────────────────────────────────────────────────────────────

SAMPLE_HTML = """
<!DOCTYPE html>
<html>
<body>
  <article class="product_pod">
    <h3><a href="../a-light-in-the-attic_1000/index.html" title="A Light in the Attic">A Light in the ...</a></h3>
    <p class="price_color">£51.77</p>
    <p class="star-rating Three"></p>
    <p class="availability">In stock</p>
  </article>
  <article class="product_pod">
    <h3><a href="../tipping-the-velvet_999/index.html" title="Tipping the Velvet">Tipping the Velvet</a></h3>
    <p class="price_color">£53.74</p>
    <p class="star-rating One"></p>
    <p class="availability">In stock</p>
  </article>
</body>
</html>
"""

def make_mock_fetch_result(url="https://books.toscrape.com/catalogue/page-1.html",
                            status=200, html=SAMPLE_HTML):
    from fetcher.base_fetcher import FetchResult
    return FetchResult(url=url, status_code=status, html=html)


# ── BaseSpider Tests ──────────────────────────────────────────────────────────

class TestBaseSpider:

    def test_cannot_instantiate_directly(self):
        from spiders.base_spider import BaseSpider
        with pytest.raises(TypeError):
            BaseSpider()

    def test_concrete_spider_initializes(self):
        from spiders.example_spider import ExampleSpider
        spider = ExampleSpider()
        assert spider.name == "ExampleSpider"
        assert spider._stats["spider"] == "ExampleSpider"

    def test_default_concurrency_from_config(self):
        from spiders.example_spider import ExampleSpider
        from config.config import Config
        spider = ExampleSpider()
        assert spider.concurrency == Config.CONCURRENCY

    def test_custom_concurrency(self):
        from spiders.example_spider import ExampleSpider
        spider = ExampleSpider(concurrency=5)
        assert spider.concurrency == 5

    def test_stats_initialized_correctly(self):
        from spiders.example_spider import ExampleSpider
        spider = ExampleSpider()
        stats = spider.get_stats()
        assert stats["spider"] == "ExampleSpider"
        assert stats["urls_total"] == 0
        assert stats["urls_fetched"] == 0
        assert stats["items_scraped"] == 0
        assert stats["items_saved"] == 0

    def test_start_run_sets_timestamp(self):
        from spiders.example_spider import ExampleSpider
        spider = ExampleSpider()
        urls = ["https://example.com/1", "https://example.com/2"]
        spider.start_run(urls)
        assert spider._stats["started_at"] is not None
        assert spider._stats["urls_total"] == 2

    def test_finish_run_sets_timestamp(self):
        from spiders.example_spider import ExampleSpider
        spider = ExampleSpider()
        spider.start_run([])
        spider.finish_run()
        assert spider._stats["finished_at"] is not None

    def test_fetch_updates_stats(self):
        from spiders.example_spider import ExampleSpider
        spider = ExampleSpider()

        async def run():
            mock_result = make_mock_fetch_result()
            with patch.object(spider.fetcher, "async_fetch",
                              return_value=mock_result):
                return await spider.fetch("https://books.toscrape.com")

        result = asyncio.run(run())
        assert spider._stats["urls_fetched"] == 1
        assert spider._stats["urls_failed"] == 0

    def test_fetch_failed_updates_stats(self):
        from spiders.example_spider import ExampleSpider
        from fetcher.base_fetcher import FetchResult
        spider = ExampleSpider()

        async def run():
            failed = FetchResult(url="https://example.com", status_code=500,
                                 error="Server error")
            with patch.object(spider.fetcher, "async_fetch",
                              return_value=failed):
                return await spider.fetch("https://example.com")

        asyncio.run(run())
        assert spider._stats["urls_failed"] == 1
        assert len(spider._stats["errors"]) == 1

    def test_parse_updates_items_scraped(self):
        from spiders.example_spider import ExampleSpider
        spider = ExampleSpider()
        spider.parse(SAMPLE_HTML, url="https://example.com")
        assert spider._stats["items_scraped"] > 0

    def test_save_updates_items_saved(self):
        from spiders.example_spider import ExampleSpider
        from storage.base_storage import SaveResult
        spider = ExampleSpider()

        items = [{"title": "Book A", "url": "https://example.com/1"}]

        async def run():
            with patch.object(spider.storage, "save",
                              return_value=SaveResult(success=True, rows_saved=1,
                                                      backend="test")):
                return await spider.save(items)

        saved = asyncio.run(run())
        assert saved == 1
        assert spider._stats["items_saved"] == 1

    def test_default_storage_is_sqlite(self):
        from spiders.example_spider import ExampleSpider
        from storage.sqlite_storage import SqliteStorage
        spider = ExampleSpider()
        assert isinstance(spider.storage, SqliteStorage)

    def test_default_parser_is_bs4(self):
        from spiders.example_spider import ExampleSpider
        from parser.bs4_parser import BS4Parser
        spider = ExampleSpider()
        assert isinstance(spider.parser, BS4Parser)

    def test_default_fetcher_is_async(self):
        from spiders.example_spider import ExampleSpider
        from fetcher.async_fetcher import AsyncFetcher
        spider = ExampleSpider()
        assert isinstance(spider.fetcher, AsyncFetcher)

    def test_custom_storage_injected(self):
        from spiders.example_spider import ExampleSpider
        from storage.csv_storage import CsvStorage
        custom = CsvStorage(filepath="data/test.csv")
        spider = ExampleSpider(storage=custom)
        assert isinstance(spider.storage, CsvStorage)

    def test_context_manager(self):
        from spiders.example_spider import ExampleSpider
        spider = ExampleSpider()

        async def run():
            async with spider:
                pass   # just enter and exit

        asyncio.run(run())   # should not raise

    def test_repr(self):
        from spiders.example_spider import ExampleSpider
        spider = ExampleSpider(concurrency=5)
        assert "ExampleSpider" in repr(spider)
        assert "5" in repr(spider)


# ── ExampleSpider Tests ───────────────────────────────────────────────────────

class TestExampleSpider:

    def test_run_returns_stats(self):
        from spiders.example_spider import ExampleSpider
        from storage.base_storage import SaveResult
        spider = ExampleSpider()

        async def mock_fetch(url, **kwargs):
            return make_mock_fetch_result(url=url)

        async def mock_save(items, **kwargs):
            return SaveResult(success=True, rows_saved=len(items), backend="test")

        async def run():
            with patch.object(spider.fetcher, "async_fetch", side_effect=mock_fetch):
                with patch.object(spider.storage, "save", side_effect=mock_save):
                    return await spider.run(urls=[
                        "https://books.toscrape.com/catalogue/page-1.html"
                    ])

        stats = asyncio.run(run())
        assert isinstance(stats, dict)
        assert stats["spider"] == "ExampleSpider"
        assert stats["urls_fetched"] == 1
        assert stats["urls_failed"] == 0

    def test_run_scrapes_items(self):
        from spiders.example_spider import ExampleSpider
        from storage.base_storage import SaveResult
        spider = ExampleSpider()

        async def mock_fetch(url, **kwargs):
            return make_mock_fetch_result(url=url)

        async def mock_save(items, **kwargs):
            return SaveResult(success=True, rows_saved=len(items), backend="test")

        async def run():
            with patch.object(spider.fetcher, "async_fetch", side_effect=mock_fetch):
                with patch.object(spider.storage, "save", side_effect=mock_save):
                    return await spider.run(urls=[
                        "https://books.toscrape.com/catalogue/page-1.html"
                    ])

        stats = asyncio.run(run())
        assert stats["items_scraped"] > 0
        assert stats["items_saved"] > 0

    def test_run_handles_failed_fetch(self):
        from spiders.example_spider import ExampleSpider
        from fetcher.base_fetcher import FetchResult
        spider = ExampleSpider()

        async def mock_fetch(url, **kwargs):
            return FetchResult(url=url, status_code=503, error="Service unavailable")

        async def run():
            with patch.object(spider.fetcher, "async_fetch", side_effect=mock_fetch):
                return await spider.run(urls=[
                    "https://books.toscrape.com/catalogue/page-1.html"
                ])

        stats = asyncio.run(run())
        assert stats["urls_failed"] == 1
        assert stats["items_saved"] == 0

    def test_run_with_defaults(self):
        from spiders.example_spider import ExampleSpider
        from storage.base_storage import SaveResult
        spider = ExampleSpider()

        async def mock_fetch(url, **kwargs):
            return make_mock_fetch_result(url=url)

        async def mock_save(items, **kwargs):
            return SaveResult(success=True, rows_saved=len(items), backend="test")

        async def run():
            with patch.object(spider.fetcher, "async_fetch", side_effect=mock_fetch):
                with patch.object(spider.storage, "save", side_effect=mock_save):
                    return await spider.run()   # no URLs — uses DEFAULT_URLS

        stats = asyncio.run(run())
        assert stats["urls_fetched"] == 1   # one default URL

    def test_build_page_urls(self):
        from spiders.example_spider import ExampleSpider
        urls = ExampleSpider.build_page_urls(total_pages=5)
        assert len(urls) == 5
        assert "page-1.html" in urls[0]
        assert "page-5.html" in urls[4]

    def test_build_page_urls_custom_start(self):
        from spiders.example_spider import ExampleSpider
        urls = ExampleSpider.build_page_urls(total_pages=3, start_page=4)
        assert "page-4.html" in urls[0]
        assert "page-6.html" in urls[2]

    def test_run_multiple_pages(self):
        from spiders.example_spider import ExampleSpider
        from storage.base_storage import SaveResult
        spider = ExampleSpider()

        async def mock_fetch(url, **kwargs):
            return make_mock_fetch_result(url=url)

        async def mock_save(items, **kwargs):
            return SaveResult(success=True, rows_saved=len(items), backend="test")

        urls = ExampleSpider.build_page_urls(total_pages=3)

        async def run():
            with patch.object(spider.fetcher, "async_fetch", side_effect=mock_fetch):
                with patch.object(spider.storage, "save", side_effect=mock_save):
                    return await spider.run(urls=urls)

        stats = asyncio.run(run())
        assert stats["urls_fetched"] == 3
        assert stats["items_scraped"] >= 6   # 2 items per page * 3 pages


# ── BatchSpider Tests ─────────────────────────────────────────────────────────

class TestBatchSpider:

    def test_initializes_correctly(self):
        from spiders.batch_spider import BatchSpider
        spider = BatchSpider(concurrency=5)
        assert spider.name == "BatchSpider"
        assert spider.concurrency == 5
        assert spider._delta_scraping is True

    def test_delta_scraping_can_be_disabled(self):
        from spiders.batch_spider import BatchSpider
        spider = BatchSpider(delta_scraping=False)
        assert spider._delta_scraping is False

    def test_stats_has_batch_fields(self):
        from spiders.batch_spider import BatchSpider
        spider = BatchSpider()
        stats = spider.get_stats()
        assert "urls_skipped_checkpoint" in stats
        assert "urls_skipped_unchanged" in stats
        assert "chunks_processed" in stats

    def test_run_with_no_urls(self):
        from spiders.batch_spider import BatchSpider
        spider = BatchSpider()

        async def run():
            return await spider.run(urls=[])

        stats = asyncio.run(run())
        assert stats["urls_total"] == 0

    def test_run_returns_stats(self, tmp_path):
        from spiders.batch_spider import BatchSpider
        from storage.base_storage import SaveResult
        from fetcher.base_fetcher import FetchResult

        spider = BatchSpider(
            checkpoint_db=str(tmp_path / "cp.db"),
            delta_scraping=False,
        )

        async def mock_fetch_batch(urls, on_result=None, prepare=True):
            results = []
            for url in urls:
                r = FetchResult(url=url, status_code=200, html=SAMPLE_HTML)
                if on_result:
                    await on_result(r)
                results.append(r)
            return results

        async def mock_save(items, **kwargs):
            return SaveResult(success=True, rows_saved=len(items), backend="test")

        async def run():
            with patch.object(
                spider._BatchSpider__class__ if hasattr(spider, '_BatchSpider__class__') else BatchSpider,
                "run", wraps=spider.run
            ):
                with patch("spiders.batch_spider.BatchFetcher") as mock_bf_class:
                    mock_bf = AsyncMock()
                    mock_bf.fetch_batch = mock_fetch_batch
                    mock_bf.__aenter__ = AsyncMock(return_value=mock_bf)
                    mock_bf.__aexit__ = AsyncMock(return_value=False)
                    mock_bf_class.return_value = mock_bf

                    with patch.object(spider.storage, "save", side_effect=mock_save):
                        return await spider.run(urls=[
                            "https://books.toscrape.com/catalogue/page-1.html",
                            "https://books.toscrape.com/catalogue/page-2.html",
                        ])

        stats = asyncio.run(run())
        assert isinstance(stats, dict)
        assert stats["spider"] == "BatchSpider"

    def test_reset_checkpoints(self, tmp_path):
        from spiders.batch_spider import BatchSpider
        spider = BatchSpider(checkpoint_db=str(tmp_path / "cp.db"))

        async def run():
            # Init checkpoint manager
            cp = await spider._get_checkpoint_manager()
            await cp.mark_done("https://example.com/1")
            stats_before = await cp.get_stats()
            assert stats_before["done"] == 1

            # Reset
            await spider.reset_checkpoints()
            stats_after = await cp.get_stats()
            assert stats_after["done"] == 0

        asyncio.run(run())

    def test_get_checkpoint_stats(self, tmp_path):
        from spiders.batch_spider import BatchSpider
        spider = BatchSpider(checkpoint_db=str(tmp_path / "cp.db"))

        async def run():
            cp = await spider._get_checkpoint_manager()
            await cp.mark_done("https://example.com/1")
            await cp.mark_done("https://example.com/2")
            await cp.mark_failed("https://example.com/3", reason="timeout")
            return await spider.get_checkpoint_stats()

        stats = asyncio.run(run())
        assert stats["done"] == 2
        assert stats["failed"] == 1
        assert stats["total_seen"] == 3
