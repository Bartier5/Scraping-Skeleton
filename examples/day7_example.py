# ── examples/day7_example.py ──────────────────────────────────────────────────
# Day 7 mini example — full middleware stack demo.
# Shows retry, proxy, and logging middleware working in a chain
# with real and simulated requests.
#
# Run with: python examples/day7_example.py

import sys
import os
import asyncio
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from utils.logger import log
from utils.helpers import ensure_dir
from fetcher.base_fetcher import FetchResult
from middleware.base_middleware import MiddlewareChain, RequestContext
from middleware.retry_middleware import RetryMiddleware
from middleware.proxy_middleware import ProxyMiddleware
from middleware.logging_middleware import LoggingMiddleware


async def main():
    ensure_dir("logs")
    ensure_dir("data")

    log.info("=" * 60)
    log.info("Day 7 — Middleware Stack Demo")
    log.info("=" * 60)

    # ── 1. LoggingMiddleware alone ────────────────────────────────────────────
    log.info("1. LoggingMiddleware — timing every request:")

    chain = MiddlewareChain([LoggingMiddleware(log_html_preview=True)])

    async def real_fetch(ctx: RequestContext) -> FetchResult:
        """Simulates a real fetch with slight delay."""
        import aiohttp, ssl
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        import aiodns
        resolver = aiohttp.AsyncResolver(nameservers=["8.8.8.8", "8.8.4.4"])
        connector = aiohttp.TCPConnector(resolver=resolver, ssl=ssl_ctx, use_dns_cache=False)
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(ctx.url) as resp:
                html = await resp.text(encoding="utf-8", errors="replace")
                return FetchResult(url=ctx.url, status_code=resp.status, html=html)

    ctx = RequestContext(url="https://books.toscrape.com")
    response = await chain.process(ctx, real_fetch)
    log.info("  Elapsed: {}ms | Status: {} | Chars: {}",
             response.metadata.get("elapsed_ms"),
             response.result.status_code,
             len(response.result.html))

    # ── 2. ProxyMiddleware — injection and rotation ───────────────────────────
    log.info("2. ProxyMiddleware — proxy rotation across 5 requests:")

    fake_proxies = [
        "http://proxy1.example.com:8080",
        "http://proxy2.example.com:8080",
        "http://proxy3.example.com:8080",
    ]

    proxy_mw = ProxyMiddleware(proxies=fake_proxies, strategy="round_robin")
    chain2 = MiddlewareChain([LoggingMiddleware(), proxy_mw])

    injected_proxies = []

    async def capture_proxy_fetch(ctx: RequestContext) -> FetchResult:
        """Records which proxy was injected, returns a fake success."""
        injected_proxies.append(ctx.proxy)
        log.debug("  Fetch called with proxy: {}", ctx.proxy)
        return FetchResult(url=ctx.url, status_code=200, html="<html>ok</html>")

    for i in range(1, 6):
        ctx = RequestContext(url=f"https://example.com/page-{i}")
        await chain2.process(ctx, capture_proxy_fetch)

    log.info("  Proxies used in order:")
    for i, proxy in enumerate(injected_proxies, 1):
        log.info("  Request {}: {}", i, proxy)

    log.info("  Proxy stats: {}", proxy_mw.get_stats())

    # ── 3. RetryMiddleware — 429 handling ─────────────────────────────────────
    log.info("3. RetryMiddleware — handling 429 Too Many Requests:")

    attempt_count = {"n": 0}

    async def flaky_fetch(ctx: RequestContext) -> FetchResult:
        """Returns 429 twice then succeeds — simulates rate limiting."""
        attempt_count["n"] += 1
        log.debug("  Fetch attempt {} for {}", attempt_count["n"], ctx.url)
        if attempt_count["n"] < 3:
            return FetchResult(url=ctx.url, status_code=429, html="")
        return FetchResult(url=ctx.url, status_code=200, html="<html>ok after retry</html>")

    retry_mw = RetryMiddleware(max_retries=3, base_delay=0.05)
    chain3 = MiddlewareChain([LoggingMiddleware(), retry_mw])

    # Note: RetryMiddleware marks needs_retry in metadata
    # In a full implementation the chain would loop — here we show
    # the metadata signal that would trigger the re-fetch
    ctx = RequestContext(url="https://example.com/rate-limited")
    response = await chain3.process(ctx, flaky_fetch)

    log.info("  Final status: {}", response.result.status_code)
    log.info("  needs_retry signal: {}", response.metadata.get("needs_retry"))
    log.info("  retry_attempt: {}", response.metadata.get("retry_attempt"))

    # ── 4. Full stack — all three middleware together ─────────────────────────
    log.info("4. Full middleware stack — logging + proxy + retry:")

    full_chain = MiddlewareChain([
        LoggingMiddleware(log_html_preview=False),   # first — times everything
        ProxyMiddleware(proxies=fake_proxies, strategy="round_robin"),  # injects proxy
        RetryMiddleware(max_retries=3, base_delay=0.05),   # catches failures
    ])

    log.info("  Chain: {}", full_chain)

    async def full_fetch(ctx: RequestContext) -> FetchResult:
        log.debug("  Fetcher received proxy={}", ctx.proxy)
        return FetchResult(url=ctx.url, status_code=200, html="<html>full stack</html>")

    urls = [f"https://example.com/item-{i}" for i in range(1, 4)]
    for url in urls:
        ctx = RequestContext(url=url)
        response = await full_chain.process(ctx, full_fetch)
        log.info("  {} → {}ms | proxy={} | status={}",
                 url.split("/")[-1],
                 response.metadata.get("elapsed_ms"),
                 ctx.proxy,
                 response.result.status_code)

    # ── 5. Disabling middleware at runtime ────────────────────────────────────
    log.info("5. Disabling middleware at runtime:")

    logging_mw = LoggingMiddleware()
    proxy_mw2 = ProxyMiddleware(proxies=fake_proxies)
    chain5 = MiddlewareChain([logging_mw, proxy_mw2])

    async def simple_fetch(ctx):
        return FetchResult(url=ctx.url, status_code=200, html="<html>ok</html>")

    # With proxy enabled
    ctx = RequestContext(url="https://example.com")
    response = await chain5.process(ctx, simple_fetch)
    log.info("  Proxy enabled:  proxy={}", ctx.proxy)

    # Disable proxy middleware
    proxy_mw2.disable()
    ctx2 = RequestContext(url="https://example.com")
    response = await chain5.process(ctx2, simple_fetch)
    log.info("  Proxy disabled: proxy={}", ctx2.proxy)

    log.info("=" * 60)
    log.success("Day 7 complete — full middleware stack working")
    log.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
