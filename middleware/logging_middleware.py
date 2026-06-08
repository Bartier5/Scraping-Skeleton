# ── middleware/logging_middleware.py ──────────────────────────────────────────
# Logging middleware — records every request and response.
#
# This is the observability layer of the scraper.
# Every request that goes out and every response that comes back
# gets logged with timing, status, and size information.
#
# Why middleware logging vs just logging in the fetcher?
#   Middleware logging captures the full picture across ALL fetchers.
#   It also captures retry attempts, proxy injections, and the final
#   resolved state of the request after all middleware have processed it.

import time
from middleware.base_middleware import BaseMiddleware, RequestContext, ResponseContext
from utils.logger import log


class LoggingMiddleware(BaseMiddleware):
    """
    Logs every request and response with timing and metadata.

    Attaches a start timestamp to the request context so the response
    handler can calculate exact elapsed time per request.
    """

    def __init__(
        self,
        config: dict = None,
        log_headers: bool = False,      # True = also log request/response headers
        log_html_preview: bool = False, # True = log first 100 chars of response HTML
    ):
        """
        Args:
            log_headers:      if True, logs headers on every request/response
            log_html_preview: if True, logs a preview of the returned HTML
        """
        super().__init__(config)
        self.log_headers = log_headers
        self.log_html_preview = log_html_preview
        log.debug("LoggingMiddleware initialized")

    async def process_request(self, context: RequestContext) -> RequestContext:
        """
        Logs the outgoing request and records start time.
        Start time is stored in metadata so process_response can measure elapsed.
        """
        if not self.enabled:
            return context

        # Store start time in context metadata
        context.metadata["request_start"] = time.time()

        log.debug(
            "→ REQUEST [attempt {}]: {}{}",
            context.attempt,
            context.url,
            f" via proxy" if context.proxy else ""
        )

        if self.log_headers and context.headers:
            log.debug("  Request headers: {}", dict(context.headers))

        return context

    async def process_response(self, context: ResponseContext) -> ResponseContext:
        """
        Logs the response with status, size, and elapsed time.
        """
        if not self.enabled:
            return context

        result = context.result

        # Calculate elapsed time using start time stored in request metadata
        start = context.request.metadata.get("request_start", time.time())
        elapsed = (time.time() - start) * 1000   # convert to milliseconds

        # Choose log level based on response status
        if result.success:
            log.debug(
                "← RESPONSE: {} | HTTP {} | {:.0f}ms | {} chars",
                result.url,
                result.status_code,
                elapsed,
                len(result.html),
            )
        else:
            log.warning(
                "← RESPONSE: {} | HTTP {} | {:.0f}ms | FAILED: {}",
                result.url,
                result.status_code,
                elapsed,
                result.error or "unknown error",
            )

        if self.log_headers and result.headers:
            log.debug("  Response headers: {}", dict(result.headers))

        if self.log_html_preview and result.html:
            preview = result.html[:100].replace("\n", " ").strip()
            log.debug("  HTML preview: {!r}", preview)

        # Attach timing to response metadata for monitoring/stats use
        context.metadata["elapsed_ms"] = round(elapsed, 2)

        return context
