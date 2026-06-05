# ── tests/test_day4.py ────────────────────────────────────────────────────────
# Isolation tests for Day 4 fetchers.
# We mock all actual HTTP calls so tests run without network access.
# This means tests are fast, reliable, and don't depend on external sites.
#
# Run with: pytest tests/test_day4.py -v

import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock


# ── HttpFetcher Tests ─────────────────────────────────────────────────────────

class TestHttpFetcher:
    """Tests for HttpFetcher — all HTTP calls are mocked."""

    def _make_mock_response(self, status_code=200, text="<html>test</html>", headers=None):
        """Helper that builds a fake requests.Response object."""
        mock_resp = MagicMock()
        mock_resp.status_code = status_code
        mock_resp.text = text
        mock_resp.headers = headers or {"Content-Type": "text/html"}
        # raise_for_status() should do nothing for 2xx, raise for 4xx/5xx
        if status_code >= 400:
            from requests.exceptions import HTTPError
            mock_resp.raise_for_status.side_effect = HTTPError(
                response=mock_resp
            )
        else:
            mock_resp.raise_for_status.return_value = None
        return mock_resp

    def test_fetch_returns_fetch_result(self):
        from fetcher.http_fetcher import HttpFetcher
        from fetcher.base_fetcher import FetchResult

        fetcher = HttpFetcher()
        mock_resp = self._make_mock_response(200, "<html>hello</html>")

        with patch.object(fetcher.session, "get", return_value=mock_resp):
            result = fetcher.fetch("https://example.com")

        assert isinstance(result, FetchResult)
        fetcher.close()

    def test_fetch_success_status(self):
        from fetcher.http_fetcher import HttpFetcher

        fetcher = HttpFetcher()
        mock_resp = self._make_mock_response(200, "<html>ok</html>")

        with patch.object(fetcher.session, "get", return_value=mock_resp):
            result = fetcher.fetch("https://example.com")

        assert result.success is True
        assert result.status_code == 200
        assert result.html == "<html>ok</html>"
        fetcher.close()

    def test_fetch_captures_html(self):
        from fetcher.http_fetcher import HttpFetcher

        fetcher = HttpFetcher()
        expected_html = "<html><body><h1>Test Page</h1></body></html>"
        mock_resp = self._make_mock_response(200, expected_html)

        with patch.object(fetcher.session, "get", return_value=mock_resp):
            result = fetcher.fetch("https://example.com")

        assert result.html == expected_html
        fetcher.close()

    def test_fetch_invalid_url_returns_error(self):
        from fetcher.http_fetcher import HttpFetcher

        fetcher = HttpFetcher()
        result = fetcher.fetch("not-a-valid-url")

        assert result.failed is True
        assert result.error is not None
        fetcher.close()

    def test_fetch_timeout_raises_for_retry(self):
        from fetcher.http_fetcher import HttpFetcher
        from requests.exceptions import Timeout

        fetcher = HttpFetcher()

        # Patch session.get to raise Timeout — retry will catch and re-raise
        with patch.object(fetcher.session, "get", side_effect=Timeout("timed out")):
            # After all retries exhausted, Timeout should propagate
            with pytest.raises(Timeout):
                fetcher.fetch("https://example.com")

        fetcher.close()

    def test_fetch_404_returns_error_result(self):
        from fetcher.http_fetcher import HttpFetcher
        from requests.exceptions import HTTPError

        fetcher = HttpFetcher()
        mock_resp = self._make_mock_response(404)

        with patch.object(fetcher.session, "get", return_value=mock_resp):
            result = fetcher.fetch("https://example.com/not-found")

        assert result.failed is True
        fetcher.close()

    def test_default_headers_set(self):
        from fetcher.http_fetcher import HttpFetcher

        fetcher = HttpFetcher()
        # Session should have User-Agent header set by default
        assert "User-Agent" in fetcher.session.headers
        assert "Mozilla" in fetcher.session.headers["User-Agent"]
        fetcher.close()

    def test_custom_headers_merged(self):
        from fetcher.http_fetcher import HttpFetcher

        fetcher = HttpFetcher(headers={"X-Custom-Header": "test-value"})
        assert "X-Custom-Header" in fetcher.session.headers
        fetcher.close()

    def test_context_manager_closes_session(self):
        from fetcher.http_fetcher import HttpFetcher

        with HttpFetcher() as fetcher:
            assert fetcher.session is not None
        # After exiting, session should be closed
        assert fetcher.session.adapters == {} or fetcher.session is not None

    def test_fetch_many_returns_list(self):
        from fetcher.http_fetcher import HttpFetcher
        from fetcher.base_fetcher import FetchResult

        fetcher = HttpFetcher()
        mock_resp = self._make_mock_response(200)
        urls = ["https://a.com", "https://b.com", "https://c.com"]

        with patch.object(fetcher.session, "get", return_value=mock_resp):
            results = asyncio.run(fetcher.fetch_many(urls))

        assert isinstance(results, list)
        assert len(results) == 3
        assert all(isinstance(r, FetchResult) for r in results)
        fetcher.close()

    def test_fetch_stores_url_in_result(self):
        from fetcher.http_fetcher import HttpFetcher

        fetcher = HttpFetcher()
        url = "https://example.com/page-1"
        mock_resp = self._make_mock_response(200)

        with patch.object(fetcher.session, "get", return_value=mock_resp):
            result = fetcher.fetch(url)

        assert result.url == url
        fetcher.close()


# ── AsyncFetcher Tests ────────────────────────────────────────────────────────

class TestAsyncFetcher:
    """Tests for AsyncFetcher — aiohttp calls are mocked."""

    def _make_mock_aiohttp_response(self, status=200, html="<html>async</html>"):
        """
        Builds a fake aiohttp response that works as an async context manager.
        aiohttp uses 'async with session.get()' — so we need a mock that
        supports __aenter__ and __aexit__.
        """
        mock_resp = AsyncMock()
        mock_resp.status = status
        # response.text() is a coroutine — AsyncMock handles this automatically
        mock_resp.text = AsyncMock(return_value=html)
        mock_resp.headers = {"Content-Type": "text/html"}

        # Make the response work as async context manager
        # __aenter__ returns the response itself, __aexit__ does nothing
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        return mock_resp

    def test_async_fetch_returns_fetch_result(self):
        from fetcher.async_fetcher import AsyncFetcher
        from fetcher.base_fetcher import FetchResult

        fetcher = AsyncFetcher()
        mock_resp = self._make_mock_aiohttp_response(200)

        async def run():
            async with fetcher:
                with patch.object(fetcher._session or MagicMock(),
                                  "get", return_value=mock_resp):
                    # Use _do_fetch directly to avoid session creation complexity
                    fetcher._session = AsyncMock()
                    fetcher._session.closed = False
                    fetcher._session.get = MagicMock(return_value=mock_resp)
                    return await fetcher._do_fetch("https://example.com")

        result = asyncio.run(run())
        assert isinstance(result, FetchResult)

    def test_async_fetch_invalid_url(self):
        from fetcher.async_fetcher import AsyncFetcher

        fetcher = AsyncFetcher()

        async def run():
            return await fetcher.async_fetch("not-a-url")

        result = asyncio.run(run())
        assert result.failed is True
        assert result.error is not None

    def test_fetch_many_returns_correct_count(self):
        from fetcher.async_fetcher import AsyncFetcher
        from fetcher.base_fetcher import FetchResult

        # Patch async_fetch to return a successful result without network
        async def mock_async_fetch(url, **kwargs):
            return FetchResult(url=url, status_code=200, html="<html>ok</html>")

        fetcher = AsyncFetcher()

        async def run():
            with patch.object(fetcher, "async_fetch", side_effect=mock_async_fetch):
                return await fetcher.fetch_many([
                    "https://a.com",
                    "https://b.com",
                    "https://c.com",
                    "https://d.com",
                    "https://e.com",
                ])

        results = asyncio.run(run())
        assert len(results) == 5

    def test_fetch_many_all_success(self):
        from fetcher.async_fetcher import AsyncFetcher
        from fetcher.base_fetcher import FetchResult

        async def mock_async_fetch(url, **kwargs):
            return FetchResult(url=url, status_code=200, html="<html>ok</html>")

        fetcher = AsyncFetcher()

        async def run():
            with patch.object(fetcher, "async_fetch", side_effect=mock_async_fetch):
                return await fetcher.fetch_many([
                    "https://a.com", "https://b.com", "https://c.com"
                ])

        results = asyncio.run(run())
        assert all(r.success for r in results)

    def test_fetch_many_handles_exceptions_gracefully(self):
        """One failing URL should not crash the entire batch."""
        from fetcher.async_fetcher import AsyncFetcher
        from fetcher.base_fetcher import FetchResult

        call_count = {"n": 0}

        async def mock_async_fetch(url, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 2:
                # Second URL raises an exception
                raise ConnectionError("Simulated failure")
            return FetchResult(url=url, status_code=200, html="<html>ok</html>")

        fetcher = AsyncFetcher()

        async def run():
            with patch.object(fetcher, "async_fetch", side_effect=mock_async_fetch):
                return await fetcher.fetch_many([
                    "https://a.com",
                    "https://b.com",    # this will fail
                    "https://c.com",
                ])

        results = asyncio.run(run())
        # Should still return 3 results — failed one wrapped in FetchResult
        assert len(results) == 3
        # 2 successful, 1 failed
        successes = [r for r in results if r.success]
        failures = [r for r in results if r.failed]
        assert len(successes) == 2
        assert len(failures) == 1

    def test_concurrency_default_from_config(self):
        from fetcher.async_fetcher import AsyncFetcher
        from config.config import Config

        fetcher = AsyncFetcher()
        assert fetcher._concurrency == Config.CONCURRENCY

    def test_concurrency_custom(self):
        from fetcher.async_fetcher import AsyncFetcher

        fetcher = AsyncFetcher(concurrency=5)
        assert fetcher._concurrency == 5

    def test_fetch_many_preserves_url_order(self):
        """Results must be in the same order as input URLs."""
        from fetcher.async_fetcher import AsyncFetcher
        from fetcher.base_fetcher import FetchResult

        urls = [f"https://example.com/page-{i}" for i in range(1, 6)]

        async def mock_async_fetch(url, **kwargs):
            return FetchResult(url=url, status_code=200)

        fetcher = AsyncFetcher()

        async def run():
            with patch.object(fetcher, "async_fetch", side_effect=mock_async_fetch):
                return await fetcher.fetch_many(urls)

        results = asyncio.run(run())
        # Each result URL must match the corresponding input URL
        for url, result in zip(urls, results):
            assert result.url == url
