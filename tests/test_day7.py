# ── tests/test_day7.py ────────────────────────────────────────────────────────
# Isolation tests for Day 7: RetryMiddleware, ProxyMiddleware, LoggingMiddleware
# Run with: pytest tests/test_day7.py -v

import pytest
import asyncio
from unittest.mock import patch, MagicMock


# ── Shared helpers ────────────────────────────────────────────────────────────

def make_request_ctx(url="https://example.com"):
    from middleware.base_middleware import RequestContext
    return RequestContext(url=url)

def make_response_ctx(url="https://example.com", status=200, html="<html>ok</html>", error=None):
    from middleware.base_middleware import RequestContext, ResponseContext
    from fetcher.base_fetcher import FetchResult
    result = FetchResult(url=url, status_code=status, html=html, error=error)
    request = RequestContext(url=url)
    return ResponseContext(result=result, request=request)


# ── RetryMiddleware Tests ─────────────────────────────────────────────────────

class TestRetryMiddleware:

    def test_initializes_correctly(self):
        from middleware.retry_middleware import RetryMiddleware
        mw = RetryMiddleware(max_retries=5, base_delay=2.0)
        assert mw.max_retries == 5
        assert mw.base_delay == 2.0

    def test_default_retry_codes(self):
        from middleware.retry_middleware import RetryMiddleware
        mw = RetryMiddleware()
        assert 429 in mw.retry_codes
        assert 503 in mw.retry_codes
        assert 500 in mw.retry_codes

    def test_process_request_passthrough(self):
        from middleware.retry_middleware import RetryMiddleware
        mw = RetryMiddleware()
        ctx = make_request_ctx()

        async def run():
            return await mw.process_request(ctx)

        result = asyncio.run(run())
        assert result.url == "https://example.com"

    def test_success_response_not_retried(self):
        from middleware.retry_middleware import RetryMiddleware
        mw = RetryMiddleware()
        ctx = make_response_ctx(status=200)

        async def run():
            return await mw.process_response(ctx)

        result = asyncio.run(run())
        assert result.metadata.get("needs_retry") is not True

    def test_429_marks_needs_retry(self):
        from middleware.retry_middleware import RetryMiddleware
        mw = RetryMiddleware(max_retries=3, base_delay=0.01)
        ctx = make_response_ctx(status=429)
        ctx.request.attempt = 1

        async def run():
            return await mw.process_response(ctx)

        result = asyncio.run(run())
        assert result.metadata.get("needs_retry") is True

    def test_503_marks_needs_retry(self):
        from middleware.retry_middleware import RetryMiddleware
        mw = RetryMiddleware(max_retries=3, base_delay=0.01)
        ctx = make_response_ctx(status=503)
        ctx.request.attempt = 1

        async def run():
            return await mw.process_response(ctx)

        result = asyncio.run(run())
        assert result.metadata.get("needs_retry") is True

    def test_gives_up_after_max_retries(self):
        from middleware.retry_middleware import RetryMiddleware
        mw = RetryMiddleware(max_retries=3, base_delay=0.01)
        ctx = make_response_ctx(status=503)
        ctx.request.attempt = 3   # already at max

        async def run():
            return await mw.process_response(ctx)

        result = asyncio.run(run())
        # Should NOT mark needs_retry — max attempts reached
        assert result.metadata.get("needs_retry") is not True

    def test_200_never_retried(self):
        from middleware.retry_middleware import RetryMiddleware
        mw = RetryMiddleware()
        ctx = make_response_ctx(status=200)

        async def run():
            return await mw.process_response(ctx)

        result = asyncio.run(run())
        assert "needs_retry" not in result.metadata

    def test_disabled_middleware_skips(self):
        from middleware.retry_middleware import RetryMiddleware
        mw = RetryMiddleware(max_retries=3, base_delay=0.01)
        mw.disable()
        ctx = make_response_ctx(status=503)

        async def run():
            return await mw.process_response(ctx)

        result = asyncio.run(run())
        assert result.metadata.get("needs_retry") is not True


# ── ProxyMiddleware Tests ─────────────────────────────────────────────────────

class TestProxyMiddleware:

    def test_initializes_with_proxies(self):
        from middleware.proxy_middleware import ProxyMiddleware
        mw = ProxyMiddleware(proxies=["http://proxy1:8080", "http://proxy2:8080"])
        assert len(mw._proxies) == 2

    def test_initializes_empty(self):
        from middleware.proxy_middleware import ProxyMiddleware
        mw = ProxyMiddleware()
        assert mw._proxies == []

    def test_round_robin_rotation(self):
        from middleware.proxy_middleware import ProxyMiddleware
        proxies = ["http://p1:8080", "http://p2:8080", "http://p3:8080"]
        mw = ProxyMiddleware(proxies=proxies, strategy="round_robin")
        # Should cycle through in order
        assert mw._get_proxy() == "http://p1:8080"
        assert mw._get_proxy() == "http://p2:8080"
        assert mw._get_proxy() == "http://p3:8080"
        assert mw._get_proxy() == "http://p1:8080"   # wraps around

    def test_random_strategy_returns_from_pool(self):
        from middleware.proxy_middleware import ProxyMiddleware
        proxies = ["http://p1:8080", "http://p2:8080"]
        mw = ProxyMiddleware(proxies=proxies, strategy="random")
        proxy = mw._get_proxy()
        assert proxy in proxies

    def test_sticky_same_domain_same_proxy(self):
        from middleware.proxy_middleware import ProxyMiddleware
        proxies = ["http://p1:8080", "http://p2:8080"]
        mw = ProxyMiddleware(proxies=proxies, strategy="sticky")
        p1 = mw._get_proxy("amazon.com")
        p2 = mw._get_proxy("amazon.com")
        assert p1 == p2   # same domain → same proxy

    def test_sticky_different_domains_may_differ(self):
        from middleware.proxy_middleware import ProxyMiddleware
        proxies = ["http://p1:8080", "http://p2:8080", "http://p3:8080"]
        mw = ProxyMiddleware(proxies=proxies, strategy="sticky")
        mw._domain_map = {"amazon.com": "http://p1:8080", "ebay.com": "http://p2:8080"}
        assert mw._get_proxy("amazon.com") != mw._get_proxy("ebay.com")

    def test_process_request_injects_proxy(self):
        from middleware.proxy_middleware import ProxyMiddleware
        mw = ProxyMiddleware(proxies=["http://proxy1:8080"])
        ctx = make_request_ctx()

        async def run():
            return await mw.process_request(ctx)

        result = asyncio.run(run())
        assert result.proxy == "http://proxy1:8080"

    def test_process_request_empty_pool_no_proxy(self):
        from middleware.proxy_middleware import ProxyMiddleware
        mw = ProxyMiddleware(proxies=[])
        ctx = make_request_ctx()

        async def run():
            return await mw.process_request(ctx)

        result = asyncio.run(run())
        assert result.proxy is None

    def test_407_marks_proxy_blocked(self):
        from middleware.proxy_middleware import ProxyMiddleware
        mw = ProxyMiddleware(proxies=["http://proxy1:8080"])
        ctx = make_response_ctx(status=407)

        async def run():
            return await mw.process_response(ctx)

        result = asyncio.run(run())
        assert result.metadata.get("proxy_blocked") is True

    def test_add_proxy(self):
        from middleware.proxy_middleware import ProxyMiddleware
        mw = ProxyMiddleware(proxies=["http://p1:8080"])
        mw.add_proxy("http://p2:8080")
        assert len(mw._proxies) == 2

    def test_remove_proxy(self):
        from middleware.proxy_middleware import ProxyMiddleware
        mw = ProxyMiddleware(proxies=["http://p1:8080", "http://p2:8080"])
        mw.remove_proxy("http://p1:8080")
        assert len(mw._proxies) == 1
        assert "http://p1:8080" not in mw._proxies

    def test_get_stats(self):
        from middleware.proxy_middleware import ProxyMiddleware
        mw = ProxyMiddleware(proxies=["http://p1:8080", "http://p2:8080"],
                             strategy="round_robin")
        stats = mw.get_stats()
        assert stats["pool_size"] == 2
        assert stats["strategy"] == "round_robin"

    def test_disabled_skips_injection(self):
        from middleware.proxy_middleware import ProxyMiddleware
        mw = ProxyMiddleware(proxies=["http://proxy1:8080"])
        mw.disable()
        ctx = make_request_ctx()

        async def run():
            return await mw.process_request(ctx)

        result = asyncio.run(run())
        assert result.proxy is None


# ── LoggingMiddleware Tests ───────────────────────────────────────────────────

class TestLoggingMiddleware:

    def test_initializes(self):
        from middleware.logging_middleware import LoggingMiddleware
        mw = LoggingMiddleware()
        assert mw.log_headers is False
        assert mw.log_html_preview is False

    def test_process_request_adds_start_time(self):
        from middleware.logging_middleware import LoggingMiddleware
        mw = LoggingMiddleware()
        ctx = make_request_ctx()

        async def run():
            return await mw.process_request(ctx)

        result = asyncio.run(run())
        assert "request_start" in result.metadata
        assert isinstance(result.metadata["request_start"], float)

    def test_process_response_adds_elapsed_ms(self):
        from middleware.logging_middleware import LoggingMiddleware
        import time
        mw = LoggingMiddleware()
        ctx = make_response_ctx(status=200)
        ctx.request.metadata["request_start"] = time.time()

        async def run():
            return await mw.process_response(ctx)

        result = asyncio.run(run())
        assert "elapsed_ms" in result.metadata
        assert result.metadata["elapsed_ms"] >= 0

    def test_success_response_logged_without_error(self):
        from middleware.logging_middleware import LoggingMiddleware
        import time
        mw = LoggingMiddleware()
        ctx = make_response_ctx(status=200, html="<html>ok</html>")
        ctx.request.metadata["request_start"] = time.time()

        async def run():
            return await mw.process_response(ctx)

        # Should not raise any exception
        result = asyncio.run(run())
        assert result is not None

    def test_failed_response_logged_without_error(self):
        from middleware.logging_middleware import LoggingMiddleware
        import time
        mw = LoggingMiddleware()
        ctx = make_response_ctx(status=503, html="", error="Service unavailable")
        ctx.request.metadata["request_start"] = time.time()

        async def run():
            return await mw.process_response(ctx)

        result = asyncio.run(run())
        assert result is not None

    def test_disabled_passthrough(self):
        from middleware.logging_middleware import LoggingMiddleware
        import time
        mw = LoggingMiddleware()
        mw.disable()
        ctx = make_response_ctx(status=200)
        ctx.request.metadata["request_start"] = time.time()

        async def run():
            return await mw.process_response(ctx)

        result = asyncio.run(run())
        # elapsed_ms should NOT be set when disabled
        assert "elapsed_ms" not in result.metadata


# ── MiddlewareChain integration test ─────────────────────────────────────────

class TestMiddlewareChainIntegration:
    """Tests all three middleware working together in a chain."""

    def test_full_chain_success(self):
        from middleware.base_middleware import MiddlewareChain, RequestContext
        from middleware.retry_middleware import RetryMiddleware
        from middleware.proxy_middleware import ProxyMiddleware
        from middleware.logging_middleware import LoggingMiddleware
        from fetcher.base_fetcher import FetchResult

        chain = MiddlewareChain([
            LoggingMiddleware(),
            ProxyMiddleware(proxies=["http://proxy1:8080"]),
            RetryMiddleware(max_retries=3, base_delay=0.01),
        ])

        async def fake_fetch(ctx):
            # Verify proxy was injected by ProxyMiddleware
            assert ctx.proxy == "http://proxy1:8080"
            return FetchResult(url=ctx.url, status_code=200, html="<html>ok</html>")

        async def run():
            ctx = RequestContext(url="https://example.com")
            return await chain.process(ctx, fake_fetch)

        response = asyncio.run(run())
        assert response.success is True
        assert "elapsed_ms" in response.metadata   # LoggingMiddleware added this

    def test_chain_repr(self):
        from middleware.base_middleware import MiddlewareChain
        from middleware.retry_middleware import RetryMiddleware
        from middleware.proxy_middleware import ProxyMiddleware
        from middleware.logging_middleware import LoggingMiddleware

        chain = MiddlewareChain([
            LoggingMiddleware(),
            ProxyMiddleware(),
            RetryMiddleware(),
        ])
        repr_str = repr(chain)
        assert "LoggingMiddleware" in repr_str
        assert "ProxyMiddleware" in repr_str
        assert "RetryMiddleware" in repr_str
