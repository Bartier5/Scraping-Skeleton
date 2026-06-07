# ── tests/test_day5.py ────────────────────────────────────────────────────────
# Isolation tests for Day 5: BatchFetcher, BrowserFetcher, SessionManager.
# All HTTP and browser calls are mocked — no network or browser needed.
#
# Run with: pytest tests/test_day5.py -v

import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock


# ── BatchFetcher Tests ────────────────────────────────────────────────────────

class TestBatchFetcher:
    """Tests for BatchFetcher chunk-based processing."""

    def test_initializes_correctly(self):
        from fetcher.batch_fetcher import BatchFetcher
        from config.config import Config
        fetcher = BatchFetcher(concurrency=5, chunk_size=10)
        assert fetcher._concurrency == 5
        assert fetcher._chunk_size == 10

    def test_default_chunk_size_is_2x_concurrency(self):
        from fetcher.batch_fetcher import BatchFetcher
        fetcher = BatchFetcher(concurrency=8)
        assert fetcher._chunk_size == 16

    def test_fetch_batch_empty_list(self):
        from fetcher.batch_fetcher import BatchFetcher

        async def run():
            async with BatchFetcher() as fetcher:
                return await fetcher.fetch_batch([])

        results = asyncio.run(run())
        assert results == []

    def test_fetch_batch_returns_all_results(self):
        from fetcher.batch_fetcher import BatchFetcher
        from fetcher.base_fetcher import FetchResult

        async def mock_fetch_many(urls, **kwargs):
            return [FetchResult(url=u, status_code=200, html="<html>ok</html>")
                    for u in urls]

        async def run():
            fetcher = BatchFetcher(concurrency=3, chunk_size=5)
            with patch.object(fetcher._async_fetcher, "fetch_many",
                              side_effect=mock_fetch_many):
                urls = [f"https://example.com/page-{i}" for i in range(12)]
                return await fetcher.fetch_batch(urls, prepare=False)

        results = asyncio.run(run())
        assert len(results) == 12
        assert all(r.success for r in results)

    def test_fetch_batch_skips_seen_urls(self):
        from fetcher.batch_fetcher import BatchFetcher
        from fetcher.base_fetcher import FetchResult

        fetched_urls = []

        async def mock_fetch_many(urls, **kwargs):
            fetched_urls.extend(urls)
            return [FetchResult(url=u, status_code=200) for u in urls]

        async def run():
            fetcher = BatchFetcher(concurrency=3, chunk_size=10)
            with patch.object(fetcher._async_fetcher, "fetch_many",
                              side_effect=mock_fetch_many):
                urls = [f"https://example.com/page-{i}" for i in range(5)]
                skip = {"https://example.com/page-0", "https://example.com/page-2"}
                return await fetcher.fetch_batch(urls, skip_urls=skip, prepare=False)

        results = asyncio.run(run())
        # Only 3 URLs should have been fetched (5 - 2 skipped)
        assert len(fetched_urls) == 3
        assert "https://example.com/page-0" not in fetched_urls
        assert "https://example.com/page-2" not in fetched_urls

    def test_fetch_batch_calls_on_result_callback(self):
        from fetcher.batch_fetcher import BatchFetcher
        from fetcher.base_fetcher import FetchResult

        callback_results = []

        async def mock_fetch_many(urls, **kwargs):
            return [FetchResult(url=u, status_code=200, html="<html>ok</html>")
                    for u in urls]

        async def run():
            fetcher = BatchFetcher(concurrency=3, chunk_size=10)
            with patch.object(fetcher._async_fetcher, "fetch_many",
                              side_effect=mock_fetch_many):
                urls = [f"https://example.com/page-{i}" for i in range(3)]
                return await fetcher.fetch_batch(
                    urls,
                    on_result=lambda r: callback_results.append(r.url),
                    prepare=False,
                )

        asyncio.run(run())
        # Callback should have been called for each successful result
        assert len(callback_results) == 3

    def test_fetch_batch_preserves_order(self):
        from fetcher.batch_fetcher import BatchFetcher
        from fetcher.base_fetcher import FetchResult

        async def mock_fetch_many(urls, **kwargs):
            return [FetchResult(url=u, status_code=200) for u in urls]

        async def run():
            fetcher = BatchFetcher(concurrency=3, chunk_size=4)
            with patch.object(fetcher._async_fetcher, "fetch_many",
                              side_effect=mock_fetch_many):
                urls = [f"https://example.com/page-{i}" for i in range(10)]
                return await fetcher.fetch_batch(urls, prepare=False)

        results = asyncio.run(run())
        # Results must be in same order as input
        for i, result in enumerate(results):
            assert result.url == f"https://example.com/page-{i}"


# ── BrowserFetcher Tests ──────────────────────────────────────────────────────

class TestBrowserFetcher:
    """Tests for BrowserFetcher — Playwright calls are fully mocked."""

    def test_initializes_correctly(self):
        from fetcher.browser_fetcher import BrowserFetcher
        fetcher = BrowserFetcher(headless=True, concurrency=3)
        assert fetcher._headless is True
        assert fetcher._concurrency == 3

    def test_invalid_url_returns_error(self):
        from fetcher.browser_fetcher import BrowserFetcher

        async def run():
            fetcher = BrowserFetcher()
            return await fetcher.async_fetch("not-a-url")

        result = asyncio.run(run())
        assert result.failed is True
        assert result.error is not None

    def test_fetch_returns_fetch_result(self):
        from fetcher.browser_fetcher import BrowserFetcher
        from fetcher.base_fetcher import FetchResult

        # Mock the entire _do_browser_fetch to avoid launching real browser
        async def mock_do_fetch(url, wait_until, timeout, wait_for_selector):
            return FetchResult(
                url=url,
                status_code=200,
                html="<html><body>JS rendered content</body></html>",
            )

        async def run():
            fetcher = BrowserFetcher()
            with patch.object(fetcher, "_do_browser_fetch",
                              side_effect=mock_do_fetch):
                return await fetcher.async_fetch("https://example.com")

        result = asyncio.run(run())
        assert isinstance(result, FetchResult)
        assert result.success is True
        assert "JS rendered content" in result.html

    def test_fetch_many_returns_correct_count(self):
        from fetcher.browser_fetcher import BrowserFetcher
        from fetcher.base_fetcher import FetchResult

        async def mock_async_fetch(url, **kwargs):
            return FetchResult(url=url, status_code=200, html="<html>ok</html>")

        async def run():
            fetcher = BrowserFetcher(concurrency=2)
            with patch.object(fetcher, "async_fetch",
                              side_effect=mock_async_fetch):
                urls = ["https://a.com", "https://b.com", "https://c.com"]
                return await fetcher.fetch_many(urls)

        results = asyncio.run(run())
        assert len(results) == 3
        assert all(r.success for r in results)

    def test_default_viewport(self):
        from fetcher.browser_fetcher import BrowserFetcher
        assert BrowserFetcher.DEFAULT_VIEWPORT == {"width": 1920, "height": 1080}

    def test_concurrency_limits_parallel_tabs(self):
        from fetcher.browser_fetcher import BrowserFetcher
        import asyncio
        fetcher = BrowserFetcher(concurrency=2)
        # Semaphore should be initialized with concurrency value
        assert fetcher._semaphore._value == 2


# ── SessionManager Tests ──────────────────────────────────────────────────────

class TestSessionConfig:
    """Tests for SessionConfig data class."""

    def test_initializes_with_required_fields(self):
        from fetcher.session_manager import SessionConfig
        cfg = SessionConfig(
            login_url="https://example.com/login",
            credentials={"username": "user", "password": "pass"},
        )
        assert cfg.login_url == "https://example.com/login"
        assert cfg.credentials == {"username": "user", "password": "pass"}

    def test_default_expiry_signals(self):
        from fetcher.session_manager import SessionConfig
        cfg = SessionConfig(
            login_url="https://example.com/login",
            credentials={},
        )
        assert 401 in cfg.expiry_signals
        assert "/login" in cfg.expiry_signals

    def test_default_session_ttl(self):
        from fetcher.session_manager import SessionConfig
        cfg = SessionConfig(
            login_url="https://example.com/login",
            credentials={},
        )
        assert cfg.session_ttl == 3600


class TestSessionManager:
    """Tests for SessionManager authentication and session handling."""

    def _make_config(self, success_check="Welcome"):
        from fetcher.session_manager import SessionConfig
        return SessionConfig(
            login_url="https://example.com/login",
            credentials={"username": "testuser", "password": "testpass"},
            success_check=success_check,
            session_ttl=3600,
        )

    def test_not_authenticated_initially(self):
        from fetcher.session_manager import SessionManager
        manager = SessionManager(self._make_config())
        assert manager._is_authenticated is False
        manager.close()

    def test_login_success(self):
        from fetcher.session_manager import SessionManager

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "Welcome to your dashboard"
        mock_response.cookies = {"session_id": "abc123"}

        manager = SessionManager(self._make_config())
        with patch.object(manager._fetcher.session, "post",
                          return_value=mock_response):
            result = manager.login()

        assert result is True
        assert manager._is_authenticated is True
        assert "session_id" in manager._cookies
        manager.close()

    def test_login_failure_bad_status(self):
        from fetcher.session_manager import SessionManager

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"
        mock_response.cookies = {}

        manager = SessionManager(self._make_config())
        with patch.object(manager._fetcher.session, "post",
                          return_value=mock_response):
            result = manager.login()

        assert result is False
        assert manager._is_authenticated is False
        manager.close()

    def test_login_failure_success_check_not_found(self):
        from fetcher.session_manager import SessionManager

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "Invalid credentials"   # success_check "Welcome" not present
        mock_response.cookies = {}

        manager = SessionManager(self._make_config(success_check="Welcome"))
        with patch.object(manager._fetcher.session, "post",
                          return_value=mock_response):
            result = manager.login()

        assert result is False
        manager.close()

    def test_get_cookies_returns_copy(self):
        from fetcher.session_manager import SessionManager
        manager = SessionManager(self._make_config())
        manager._cookies = {"session_id": "abc123", "token": "xyz"}
        cookies = manager.get_cookies()
        assert cookies == {"session_id": "abc123", "token": "xyz"}
        # Modifying the returned dict should not affect internal state
        cookies["new_key"] = "new_val"
        assert "new_key" not in manager._cookies
        manager.close()

    def test_get_cookie_header(self):
        from fetcher.session_manager import SessionManager
        manager = SessionManager(self._make_config())
        manager._cookies = {"session_id": "abc123"}
        header = manager.get_cookie_header()
        assert "session_id=abc123" in header
        manager.close()

    def test_logout_clears_state(self):
        from fetcher.session_manager import SessionManager
        manager = SessionManager(self._make_config())
        manager._is_authenticated = True
        manager._cookies = {"session_id": "abc123"}
        manager.logout()
        assert manager._is_authenticated is False
        assert manager._cookies == {}
        manager.close()

    def test_session_expiry_by_status_code(self):
        from fetcher.session_manager import SessionManager
        from fetcher.base_fetcher import FetchResult
        manager = SessionManager(self._make_config())
        manager._is_authenticated = True
        manager._login_time = 9999999999   # far future — TTL won't trigger

        expired_result = FetchResult(url="https://example.com", status_code=401)
        assert manager._is_session_expired(expired_result) is True
        manager.close()

    def test_session_not_expired_on_200(self):
        from fetcher.session_manager import SessionManager
        from fetcher.base_fetcher import FetchResult
        import time
        manager = SessionManager(self._make_config())
        manager._is_authenticated = True
        manager._login_time = time.time()   # just logged in

        good_result = FetchResult(url="https://example.com/dashboard", status_code=200)
        assert manager._is_session_expired(good_result) is False
        manager.close()
