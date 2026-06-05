# ── examples/day3_example.py ─────────────────────────────────────────────────
# Day 3 mini example — demonstrates how the base classes work together
# and how the middleware chain processes a simulated request/response.
#
# No real HTTP requests — everything is simulated so you can see
# the architecture working without any network dependency.
#
# Run with: python examples/day3_example.py

import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.logger import log
from utils.helpers import ensure_dir
from fetcher.base_fetcher import BaseFetcher, FetchResult
from parser.base_parser import BaseParser, ParseResult
from storage.base_storage import BaseStorage, SaveResult
from middleware.base_middleware import (
    BaseMiddleware, MiddlewareChain,
    RequestContext, ResponseContext,
)


# ── Minimal concrete implementations for the demo ────────────────────────────
# These simulate what the real fetcher/parser/storage will do on Days 4-11

class DemoFetcher(BaseFetcher):
    """Simulates an HTTP fetcher — returns fake HTML instead of real requests."""

    def fetch(self, url: str, **kwargs) -> FetchResult:
        log.info("  [DemoFetcher] Sync fetching: {}", url)
        return FetchResult(
            url=url,
            status_code=200,
            html=f"<html><body><h1>Page: {url}</h1><p>Price: $9.99</p></body></html>",
        )

    async def async_fetch(self, url: str, **kwargs) -> FetchResult:
        log.info("  [DemoFetcher] Async fetching: {}", url)
        await asyncio.sleep(0.05)   # simulate network latency
        return FetchResult(
            url=url,
            status_code=200,
            html=f"<html><body><h1>Async Page: {url}</h1></body></html>",
        )

    async def fetch_many(self, urls: list[str], **kwargs) -> list[FetchResult]:
        log.info("  [DemoFetcher] Batch fetching {} URLs", len(urls))
        # Run all async fetches concurrently
        tasks = [self.async_fetch(url) for url in urls]
        return await asyncio.gather(*tasks)


class DemoParser(BaseParser):
    """Simulates an HTML parser — extracts fake data from the demo HTML."""

    def parse(self, html: str, url: str = "") -> ParseResult:
        log.info("  [DemoParser] Parsing HTML from: {}", url)
        # In real life this would use BeautifulSoup — for now just fake it
        return ParseResult(
            url=url,
            data=[{"url": url, "title": "Demo Product", "price": "$9.99"}],
        )

    def extract_links(self, html: str, base_url: str = "") -> list[str]:
        # Simulates finding 2 links on the page
        return [
            f"{base_url}/page-2",
            f"{base_url}/page-3",
        ]

    def extract_text(self, html: str) -> str:
        # Simulates stripping all HTML tags
        import re
        return re.sub(r"<[^>]+>", "", html).strip()


class DemoStorage(BaseStorage):
    """Simulates a storage backend — keeps data in memory for the demo."""

    def __init__(self):
        super().__init__()
        self._store: list[dict] = []   # in-memory store

    async def save(self, data: list[dict], **kwargs) -> SaveResult:
        log.info("  [DemoStorage] Saving {} records", len(data))
        self._store.extend(data)
        return SaveResult(success=True, rows_saved=len(data), backend="demo_memory")

    async def load(self, limit: int = None, **kwargs) -> list[dict]:
        return self._store[:limit] if limit else self._store[:]

    async def exists(self, key: str, value) -> bool:
        return any(item.get(key) == value for item in self._store)

    async def clear(self) -> bool:
        self._store.clear()
        return True

    async def count(self) -> int:
        return len(self._store)


# ── Demo Middleware ────────────────────────────────────────────────────────────

class TimingMiddleware(BaseMiddleware):
    """Records how long each request takes."""

    async def process_request(self, context: RequestContext) -> RequestContext:
        import time
        # Store request start time in context metadata
        context.metadata["start_time"] = time.time()
        log.debug("  [TimingMW] Request started for: {}", context.url)
        return context

    async def process_response(self, context: ResponseContext) -> ResponseContext:
        import time
        start = context.request.metadata.get("start_time", time.time())
        elapsed = (time.time() - start) * 1000   # convert to milliseconds
        context.metadata["elapsed_ms"] = round(elapsed, 2)
        log.debug("  [TimingMW] Request completed in {:.2f}ms", elapsed)
        return context


class HeaderMiddleware(BaseMiddleware):
    """Injects default headers into every request."""

    async def process_request(self, context: RequestContext) -> RequestContext:
        # Add standard headers that make requests look more like a real browser
        context.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        log.debug("  [HeaderMW] Injected {} headers", len(context.headers))
        return context

    async def process_response(self, context: ResponseContext) -> ResponseContext:
        # Nothing to do on response — just pass through
        return context


class StatusCheckMiddleware(BaseMiddleware):
    """Logs a warning if the response status is not 200."""

    async def process_request(self, context: RequestContext) -> RequestContext:
        return context   # nothing to do on request

    async def process_response(self, context: ResponseContext) -> ResponseContext:
        if context.result.status_code != 200:
            log.warning(
                "  [StatusMW] Non-200 response: {} for {}",
                context.result.status_code,
                context.result.url,
            )
        else:
            log.debug("  [StatusMW] Response OK: {}", context.result.url)
        return context


# ── Main demo ─────────────────────────────────────────────────────────────────

async def main():
    ensure_dir("logs")
    ensure_dir("data")

    log.info("=" * 60)
    log.info("Day 3 — Base Classes Architecture Demo")
    log.info("=" * 60)

    fetcher = DemoFetcher()
    parser = DemoParser()
    storage = DemoStorage()

    # ── 1. FetchResult — success and failure states ───────────────────────────
    log.info("1. FetchResult states:")

    success = FetchResult(url="https://example.com", status_code=200, html="<html>ok</html>")
    failed = FetchResult(url="https://example.com", status_code=503, error="Service unavailable")
    pending = FetchResult(url="https://example.com", status_code=0)

    log.info("  Success (200): success={} failed={}", success.success, success.failed)
    log.info("  Failed  (503): success={} failed={}", failed.success, failed.failed)
    log.info("  Pending   (0): success={} failed={}", pending.success, pending.failed)

    # ── 2. Fetcher — sync, async, batch ──────────────────────────────────────
    log.info("2. DemoFetcher — sync, async, batch:")

    sync_result = fetcher.fetch("https://books.toscrape.com/page-1")
    log.info("  Sync:  {}", sync_result)

    async_result = await fetcher.async_fetch("https://quotes.toscrape.com/page-1")
    log.info("  Async: {}", async_result)

    batch_urls = [f"https://example.com/product-{i}" for i in range(1, 6)]
    batch_results = await fetcher.fetch_many(batch_urls)
    log.info("  Batch: {} results, all success={}",
             len(batch_results), all(r.success for r in batch_results))

    # ── 3. Parser — parse, extract_links, extract_text, safe_extract ─────────
    log.info("3. DemoParser:")

    parse_result = parser.parse(sync_result.html, url=sync_result.url)
    log.info("  ParseResult: {} items, success={}", parse_result.item_count, parse_result.success)

    links = parser.extract_links(sync_result.html, base_url="https://books.toscrape.com")
    log.info("  Extracted links: {}", links)

    text = parser.extract_text(sync_result.html)
    log.info("  Extracted text: {!r}", text)

    # safe_extract demo — one succeeds, one fails gracefully
    good = parser.safe_extract(lambda: "found it", fallback="not found")
    bad = parser.safe_extract(lambda: [][0], fallback="fallback value")
    log.info("  safe_extract (good): {}", good)
    log.info("  safe_extract (bad→fallback): {}", bad)

    # ── 4. Storage — save, load, exists, count, clear ────────────────────────
    log.info("4. DemoStorage:")

    items = [
        {"url": "https://example.com/1", "title": "Product A", "price": "$10.00"},
        {"url": "https://example.com/2", "title": "Product B", "price": "$20.00"},
        {"url": "https://example.com/3", "title": "Product C", "price": "$30.00"},
    ]

    save_result = await storage.save(items)
    log.info("  Saved: {}", save_result)

    count = await storage.count()
    log.info("  Count: {}", count)

    exists = await storage.exists("url", "https://example.com/2")
    not_exists = await storage.exists("url", "https://example.com/999")
    log.info("  exists('https://example.com/2'): {}", exists)
    log.info("  exists('https://example.com/999'): {}", not_exists)

    loaded = await storage.load(limit=2)
    log.info("  Loaded (limit=2): {} records", len(loaded))

    await storage.clear()
    log.info("  After clear, count: {}", await storage.count())

    # ── 5. Middleware chain — the full request/response cycle ─────────────────
    log.info("5. MiddlewareChain — request flows through middleware, then back:")

    chain = MiddlewareChain([
        TimingMiddleware(),       # records how long requests take
        HeaderMiddleware(),       # injects browser-like headers
        StatusCheckMiddleware(),  # logs warning on non-200 status
    ])

    log.info("  Chain: {}", chain)
    log.info("  Processing request through chain...")

    async def fake_fetch(ctx: RequestContext) -> FetchResult:
        """Simulates the fetcher — this is what sits at the end of the chain."""
        log.debug("  [Fetcher] Executing request: {}", ctx.url)
        log.debug("  [Fetcher] Headers received: {}", list(ctx.headers.keys()))
        await asyncio.sleep(0.05)
        return FetchResult(url=ctx.url, status_code=200, html="<html>response</html>")

    request_ctx = RequestContext(url="https://example.com/product-1")
    response = await chain.process(request_ctx, fake_fetch)

    log.info("  Response success: {}", response.success)
    log.info("  Elapsed time: {}ms", response.metadata.get("elapsed_ms", "N/A"))
    log.info("  Headers injected: {}", list(response.request.headers.keys()))

    # ── 6. Disabled middleware ────────────────────────────────────────────────
    log.info("6. Disabling middleware mid-chain:")

    header_mw = HeaderMiddleware()
    chain2 = MiddlewareChain([header_mw, StatusCheckMiddleware()])

    log.info("  Before disable: {}", chain2)
    header_mw.disable()
    log.info("  After disable:  HeaderMiddleware enabled={}", header_mw.enabled)

    response2 = await chain2.process(
        RequestContext(url="https://example.com/page-2"),
        fake_fetch,
    )
    # No headers should be in the request since HeaderMiddleware was disabled
    log.info("  Headers with MW disabled: {}", list(response2.request.headers.keys()))

    log.info("=" * 60)
    log.success("Day 3 complete — base class architecture validated end-to-end")
    log.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
