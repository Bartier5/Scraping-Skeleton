# ── middleware/retry_middleware.py ────────────────────────────────────────────
# Retry middleware — automatically retries failed requests.
#
# Why middleware retry vs fetcher retry?
#   The fetcher already has built-in retry for network errors.
#   This middleware handles HTTP-level failures at the middleware layer:
#   - 429 Too Many Requests (rate limited by server)
#   - 503 Service Unavailable (server temporarily down)
#   - Any configurable status code
#
#   The key difference: middleware retry runs AFTER the response arrives,
#   fetcher retry runs when the request never completes.

import asyncio


from middleware.base_middleware import BaseMiddleware, RequestContext, ResponseContext
from fetcher.base_fetcher import FetchResult
from utils.logger import log


class RetryMiddleware(BaseMiddleware):
    """
    Retries requests that return specific HTTP status codes.

    Sits in the middleware chain and intercepts responses with
    retryable status codes, re-running the request with backoff.
    """

    # Status codes that are worth retrying
    DEFAULT_RETRY_CODES = {429, 500, 502, 503, 504}

    def __init__(
        self,
        config: dict = None,
        max_retries: int = 3,
        retry_codes: set = None,
        base_delay: float = 1.0,    # seconds — doubles each attempt
    ):
        """
        Args:
            max_retries:  how many times to retry before giving up
            retry_codes:  HTTP status codes that trigger a retry
            base_delay:   initial wait time — doubles each attempt (exponential backoff)
        """
        super().__init__(config)
        self.max_retries = max_retries
        self.retry_codes = retry_codes or self.DEFAULT_RETRY_CODES
        self.base_delay = base_delay

        log.debug(
            "RetryMiddleware initialized (max_retries={}, codes={})",
            max_retries, retry_codes or self.DEFAULT_RETRY_CODES
        )

    async def process_request(self, context: RequestContext) -> RequestContext:
        """Pass through — retry logic is on the response side."""
        return context

    async def process_response(self, context: ResponseContext) -> ResponseContext:
        """
        Checks if the response status warrants a retry.
        If yes, waits with exponential backoff and re-runs the fetch.

        Special handling for 429 — checks Retry-After header if present
        and waits exactly that long before retrying.
        """
        if not self.enabled:
            return context

        result = context.result

        # Nothing to retry if request succeeded
        if result.success or result.status_code not in self.retry_codes:
            return context

        attempt = context.request.attempt

        if attempt >= self.max_retries:
            log.warning(
                "RetryMiddleware: giving up after {} attempts for {}",
                attempt, result.url
            )
            return context

        # Calculate wait time
        # Special case: 429 may include a Retry-After header
        retry_after = result.headers.get("Retry-After", None)
        if retry_after and result.status_code == 429:
            try:
                wait = float(retry_after)
                log.info(
                    "RetryMiddleware: 429 — waiting {}s (Retry-After header) for {}",
                    wait, result.url
                )
            except ValueError:
                wait = self.base_delay * (2 ** (attempt - 1))
        else:
            # Exponential backoff: 1s, 2s, 4s, 8s...
            wait = self.base_delay * (2 ** (attempt - 1))

        log.info(
            "RetryMiddleware: HTTP {} — retrying in {:.1f}s (attempt {}/{}) for {}",
            result.status_code, wait, attempt + 1, self.max_retries, result.url
        )

        await asyncio.sleep(wait)

        # Increment attempt counter on the request context
        context.request.attempt += 1

        # Signal that this response needs to be re-fetched
        # We store retry info in metadata for the chain to act on
        context.metadata["needs_retry"] = True
        context.metadata["retry_attempt"] = attempt + 1

        return context
