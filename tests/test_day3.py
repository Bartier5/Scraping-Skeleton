# ── tests/test_day3.py ────────────────────────────────────────────────────────
# Isolation tests for Day 3 base classes.
# Since ABCs can't be instantiated directly, we test them by creating
# minimal concrete implementations and verifying the contracts work correctly.
#
# Run with: pytest tests/test_day3.py -v

import pytest
import asyncio


# ── Concrete test implementations ─────────────────────────────────────────────
# These are the simplest possible implementations of each base class.
# We define them here just for testing — real implementations come Days 4-11.

class MinimalFetcher:
    """Minimal concrete fetcher for testing BaseFetcher contracts."""
    def __init__(self):
        from fetcher.base_fetcher import BaseFetcher, FetchResult
        # We can't instantiate BaseFetcher directly so we create a subclass inline
        class _Fetcher(BaseFetcher):
            def fetch(self, url, **kwargs):
                return FetchResult(url=url, status_code=200, html="<html>test</html>")

            async def async_fetch(self, url, **kwargs):
                return FetchResult(url=url, status_code=200, html="<html>test</html>")

            async def fetch_many(self, urls, **kwargs):
                return [FetchResult(url=u, status_code=200, html="<html>test</html>") for u in urls]

        self.instance = _Fetcher()


class MinimalParser:
    """Minimal concrete parser for testing BaseParser contracts."""
    def __init__(self):
        from parser.base_parser import BaseParser, ParseResult
        class _Parser(BaseParser):
            def parse(self, html, url=""):
                return ParseResult(url=url, data=[{"raw": html}])

            def extract_links(self, html, base_url=""):
                return ["https://example.com/link-1"]

            def extract_text(self, html):
                return "plain text"

        self.instance = _Parser()


class MinimalStorage:
    """Minimal concrete storage for testing BaseStorage contracts."""
    def __init__(self):
        from storage.base_storage import BaseStorage, SaveResult
        class _Storage(BaseStorage):
            def __init__(self):
                super().__init__()
                self._data = []     # in-memory store for testing

            async def save(self, data, **kwargs):
                self._data.extend(data)
                return SaveResult(success=True, rows_saved=len(data), backend="test")

            async def load(self, limit=None, **kwargs):
                return self._data[:limit] if limit else self._data

            async def exists(self, key, value):
                return any(item.get(key) == value for item in self._data)

            async def clear(self):
                self._data.clear()
                return True

            async def count(self):
                return len(self._data)

        self.instance = _Storage()


class MinimalMiddleware:
    """Minimal concrete middleware for testing BaseMiddleware contracts."""
    def __init__(self):
        from middleware.base_middleware import BaseMiddleware
        class _Middleware(BaseMiddleware):
            async def process_request(self, context):
                context.metadata["touched_by"] = "test_middleware"
                return context

            async def process_response(self, context):
                context.metadata["response_touched"] = True
                return context

        self.instance = _Middleware()


# ── FetchResult Tests ─────────────────────────────────────────────────────────

class TestFetchResult:
    """Tests for the FetchResult dataclass."""

    def test_success_property_true(self):
        from fetcher.base_fetcher import FetchResult
        result = FetchResult(url="https://example.com", status_code=200)
        assert result.success is True

    def test_success_property_false_on_error_status(self):
        from fetcher.base_fetcher import FetchResult
        result = FetchResult(url="https://example.com", status_code=404)
        assert result.success is False

    def test_success_false_when_error_present(self):
        from fetcher.base_fetcher import FetchResult
        # Even a 200 status with an error string should be considered failed
        result = FetchResult(url="https://example.com", status_code=200, error="timeout")
        assert result.success is False

    def test_failed_property(self):
        from fetcher.base_fetcher import FetchResult
        result = FetchResult(url="https://example.com", status_code=500)
        assert result.failed is True

    def test_default_values(self):
        from fetcher.base_fetcher import FetchResult
        result = FetchResult(url="https://example.com")
        # status_code defaults to 0 (never completed)
        assert result.status_code == 0
        assert result.html == ""
        assert result.headers == {}
        assert result.error is None
        assert result.metadata == {}

    def test_str_representation(self):
        from fetcher.base_fetcher import FetchResult
        result = FetchResult(url="https://example.com", status_code=200)
        s = str(result)
        assert "OK" in s
        assert "https://example.com" in s

    def test_2xx_codes_are_success(self):
        from fetcher.base_fetcher import FetchResult
        for code in [200, 201, 204, 206]:
            result = FetchResult(url="https://example.com", status_code=code)
            assert result.success is True, f"Status {code} should be success"

    def test_non_2xx_codes_are_failed(self):
        from fetcher.base_fetcher import FetchResult
        for code in [301, 400, 403, 404, 429, 500, 503]:
            result = FetchResult(url="https://example.com", status_code=code)
            assert result.failed is True, f"Status {code} should be failed"


# ── BaseFetcher Tests ─────────────────────────────────────────────────────────

class TestBaseFetcher:
    """Tests for BaseFetcher contract enforcement and shared methods."""

    def test_cannot_instantiate_abc_directly(self):
        from fetcher.base_fetcher import BaseFetcher
        # Trying to instantiate an ABC directly must raise TypeError
        with pytest.raises(TypeError):
            BaseFetcher()

    def test_concrete_subclass_works(self):
        fetcher = MinimalFetcher().instance
        assert fetcher is not None

    def test_fetch_returns_fetch_result(self):
        from fetcher.base_fetcher import FetchResult
        fetcher = MinimalFetcher().instance
        result = fetcher.fetch("https://example.com")
        assert isinstance(result, FetchResult)

    def test_async_fetch_returns_fetch_result(self):
        from fetcher.base_fetcher import FetchResult
        fetcher = MinimalFetcher().instance

        async def run():
            return await fetcher.async_fetch("https://example.com")

        result = asyncio.run(run())
        assert isinstance(result, FetchResult)

    def test_fetch_many_returns_list(self):
        fetcher = MinimalFetcher().instance
        urls = ["https://a.com", "https://b.com", "https://c.com"]

        async def run():
            return await fetcher.fetch_many(urls)

        results = asyncio.run(run())
        assert isinstance(results, list)
        assert len(results) == 3

    def test_validate_url_valid(self):
        fetcher = MinimalFetcher().instance
        assert fetcher.validate_url("https://example.com") is True

    def test_validate_url_invalid(self):
        fetcher = MinimalFetcher().instance
        assert fetcher.validate_url("not-a-url") is False

    def test_make_error_result(self):
        from fetcher.base_fetcher import FetchResult
        fetcher = MinimalFetcher().instance
        result = fetcher.make_error_result("https://example.com", ConnectionError("timeout"))
        assert isinstance(result, FetchResult)
        assert result.failed is True
        assert "timeout" in result.error


# ── ParseResult Tests ─────────────────────────────────────────────────────────

class TestParseResult:
    """Tests for the ParseResult dataclass."""

    def test_success_when_data_present(self):
        from parser.base_parser import ParseResult
        result = ParseResult(url="https://example.com", data=[{"title": "Book"}])
        assert result.success is True

    def test_failed_when_no_data(self):
        from parser.base_parser import ParseResult
        result = ParseResult(url="https://example.com", data=[])
        assert result.success is False

    def test_item_count(self):
        from parser.base_parser import ParseResult
        result = ParseResult(
            url="https://example.com",
            data=[{"a": 1}, {"b": 2}, {"c": 3}]
        )
        assert result.item_count == 3

    def test_default_values(self):
        from parser.base_parser import ParseResult
        result = ParseResult(url="https://example.com")
        assert result.data == []
        assert result.errors == []
        assert result.metadata == {}


# ── BaseParser Tests ──────────────────────────────────────────────────────────

class TestBaseParser:
    """Tests for BaseParser contract enforcement."""

    def test_cannot_instantiate_abc_directly(self):
        from parser.base_parser import BaseParser
        with pytest.raises(TypeError):
            BaseParser()

    def test_concrete_subclass_works(self):
        parser = MinimalParser().instance
        assert parser is not None

    def test_parse_returns_parse_result(self):
        from parser.base_parser import ParseResult
        parser = MinimalParser().instance
        result = parser.parse("<html>test</html>", url="https://example.com")
        assert isinstance(result, ParseResult)

    def test_extract_links_returns_list(self):
        parser = MinimalParser().instance
        links = parser.extract_links("<html><a href='/page'>link</a></html>")
        assert isinstance(links, list)

    def test_extract_text_returns_string(self):
        parser = MinimalParser().instance
        text = parser.extract_text("<html><body>hello</body></html>")
        assert isinstance(text, str)

    def test_safe_extract_returns_value(self):
        parser = MinimalParser().instance
        result = parser.safe_extract(lambda: "extracted value")
        assert result == "extracted value"

    def test_safe_extract_returns_fallback_on_error(self):
        parser = MinimalParser().instance
        # Lambda raises an exception — safe_extract should return fallback
        result = parser.safe_extract(lambda: 1 / 0, fallback="default")
        assert result == "default"

    def test_safe_extract_none_fallback(self):
        parser = MinimalParser().instance
        result = parser.safe_extract(lambda: [][0])   # IndexError
        assert result is None   # default fallback is None


# ── SaveResult Tests ──────────────────────────────────────────────────────────

class TestSaveResult:
    """Tests for the SaveResult dataclass."""

    def test_default_values(self):
        from storage.base_storage import SaveResult
        result = SaveResult()
        assert result.success is False
        assert result.rows_saved == 0
        assert result.rows_skipped == 0
        assert result.error is None

    def test_str_representation(self):
        from storage.base_storage import SaveResult
        result = SaveResult(success=True, rows_saved=5, backend="sqlite")
        s = str(result)
        assert "OK" in s
        assert "sqlite" in s
        assert "5" in s


# ── BaseStorage Tests ─────────────────────────────────────────────────────────

class TestBaseStorage:
    """Tests for BaseStorage contract enforcement."""

    def test_cannot_instantiate_abc_directly(self):
        from storage.base_storage import BaseStorage
        with pytest.raises(TypeError):
            BaseStorage()

    def test_save_returns_save_result(self):
        from storage.base_storage import SaveResult
        storage = MinimalStorage().instance

        async def run():
            return await storage.save([{"title": "Book", "price": "$9.99"}])

        result = asyncio.run(run())
        assert isinstance(result, SaveResult)
        assert result.success is True
        assert result.rows_saved == 1

    def test_load_returns_list(self):
        storage = MinimalStorage().instance

        async def run():
            await storage.save([{"title": "Book"}])
            return await storage.load()

        result = asyncio.run(run())
        assert isinstance(result, list)

    def test_exists_true(self):
        storage = MinimalStorage().instance

        async def run():
            await storage.save([{"url": "https://example.com"}])
            return await storage.exists("url", "https://example.com")

        assert asyncio.run(run()) is True

    def test_exists_false(self):
        storage = MinimalStorage().instance

        async def run():
            return await storage.exists("url", "https://not-saved.com")

        assert asyncio.run(run()) is False

    def test_clear(self):
        storage = MinimalStorage().instance

        async def run():
            await storage.save([{"a": 1}, {"b": 2}])
            await storage.clear()
            return await storage.count()

        count = asyncio.run(run())
        assert count == 0

    def test_count(self):
        storage = MinimalStorage().instance

        async def run():
            await storage.save([{"a": 1}, {"b": 2}, {"c": 3}])
            return await storage.count()

        assert asyncio.run(run()) == 3


# ── RequestContext / ResponseContext Tests ────────────────────────────────────

class TestRequestResponseContext:
    """Tests for the middleware context objects."""

    def test_request_context_defaults(self):
        from middleware.base_middleware import RequestContext
        ctx = RequestContext(url="https://example.com")
        assert ctx.url == "https://example.com"
        assert ctx.headers == {}
        assert ctx.proxy is None
        assert ctx.attempt == 1
        assert ctx.metadata == {}

    def test_response_context_success_passthrough(self):
        from middleware.base_middleware import ResponseContext
        from fetcher.base_fetcher import FetchResult, BaseFetcher
        from middleware.base_middleware import RequestContext
        result = FetchResult(url="https://example.com", status_code=200)
        request = RequestContext(url="https://example.com")
        response = ResponseContext(result=result, request=request)
        assert response.success is True


# ── BaseMiddleware Tests ──────────────────────────────────────────────────────

class TestBaseMiddleware:
    """Tests for BaseMiddleware contract enforcement."""

    def test_cannot_instantiate_abc_directly(self):
        from middleware.base_middleware import BaseMiddleware
        with pytest.raises(TypeError):
            BaseMiddleware()

    def test_process_request_modifies_context(self):
        from middleware.base_middleware import RequestContext
        mw = MinimalMiddleware().instance

        async def run():
            ctx = RequestContext(url="https://example.com")
            return await mw.process_request(ctx)

        ctx = asyncio.run(run())
        assert ctx.metadata.get("touched_by") == "test_middleware"

    def test_enable_disable(self):
        mw = MinimalMiddleware().instance
        assert mw.enabled is True
        mw.disable()
        assert mw.enabled is False
        mw.enable()
        assert mw.enabled is True


# ── MiddlewareChain Tests ─────────────────────────────────────────────────────

class TestMiddlewareChain:
    """Tests for the MiddlewareChain orchestrator."""

    def test_chain_processes_request_and_response(self):
        from middleware.base_middleware import (
            MiddlewareChain, RequestContext, BaseMiddleware
        )
        from fetcher.base_fetcher import FetchResult

        # Create two middleware that each add a marker to metadata
        class MW1(BaseMiddleware):
            async def process_request(self, ctx):
                ctx.metadata["mw1_request"] = True
                return ctx
            async def process_response(self, ctx):
                ctx.metadata["mw1_response"] = True
                return ctx

        class MW2(BaseMiddleware):
            async def process_request(self, ctx):
                ctx.metadata["mw2_request"] = True
                return ctx
            async def process_response(self, ctx):
                ctx.metadata["mw2_response"] = True
                return ctx

        chain = MiddlewareChain([MW1(), MW2()])

        async def fake_fetch(ctx):
            # Simulates the fetcher returning a successful result
            return FetchResult(url=ctx.url, status_code=200, html="<html>ok</html>")

        async def run():
            ctx = RequestContext(url="https://example.com")
            return await chain.process(ctx, fake_fetch)

        response = asyncio.run(run())
        # Both middleware should have touched the request
        assert response.request.metadata.get("mw1_request") is True
        assert response.request.metadata.get("mw2_request") is True
        # Both middleware should have touched the response
        assert response.metadata.get("mw1_response") is True
        assert response.metadata.get("mw2_response") is True

    def test_chain_add_method_chainable(self):
        from middleware.base_middleware import MiddlewareChain
        mw = MinimalMiddleware().instance
        chain = MiddlewareChain()
        # add() returns self so it can be chained
        result = chain.add(mw)
        assert result is chain
        assert len(chain.middlewares) == 1

    def test_disabled_middleware_skipped(self):
        from middleware.base_middleware import (
            MiddlewareChain, RequestContext, BaseMiddleware
        )
        from fetcher.base_fetcher import FetchResult

        class MarkerMW(BaseMiddleware):
            async def process_request(self, ctx):
                ctx.metadata["was_run"] = True
                return ctx
            async def process_response(self, ctx):
                return ctx

        mw = MarkerMW()
        mw.disable()    # disable before adding to chain
        chain = MiddlewareChain([mw])

        async def fake_fetch(ctx):
            return FetchResult(url=ctx.url, status_code=200)

        async def run():
            ctx = RequestContext(url="https://example.com")
            return await chain.process(ctx, fake_fetch)

        response = asyncio.run(run())
        # Disabled middleware should not have run
        assert response.request.metadata.get("was_run") is None
