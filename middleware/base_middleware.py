# ── middleware/base_middleware.py ─────────────────────────────────────────────
# Abstract base class for all middleware in the scraper skeleton.
#
# What is middleware?
#   Middleware sits between the spider and the fetcher — every request passes
#   THROUGH middleware before going out, and every response passes back through
#   it on the way in. Each middleware can inspect, modify, log, or even block
#   requests and responses.
#
#   Think of it like airport security:
#   Spider → [logging middleware] → [proxy middleware] → [retry middleware] → Fetcher
#   Fetcher → [retry middleware] → [proxy middleware] → [logging middleware] → Spider
#
# Why is this useful?
#   Instead of scattering retry logic, proxy injection, and logging across
#   every fetcher, middleware isolates each concern into its own class.
#   You can add, remove, or reorder middleware without touching the fetcher.
#
# Middleware that will inherit from this (Day 7):
#   - RetryMiddleware    (auto-retry on 429, 503, timeout)
#   - ProxyMiddleware    (inject proxy into every request)
#   - LoggingMiddleware  (log every request and response)

from abc import ABC, abstractmethod
from typing import Callable, Awaitable, Optional
from fetcher.base_fetcher import FetchResult   # middleware works on FetchResults
from utils.logger import log


# ── Request / Response context objects ───────────────────────────────────────

class RequestContext:
    """
    Holds all information about an outgoing request.
    Middleware can read and modify this before the request is sent.

    Think of it as the request's "passport" — it travels with the request
    and middleware can stamp, modify, or reject it.
    """

    def __init__(
        self,
        url: str,
        headers: dict = None,
        proxy: Optional[str] = None,
        timeout: int = None,
        metadata: dict = None,
    ):
        self.url = url                          # target URL
        self.headers = headers or {}            # HTTP headers to send
        self.proxy = proxy                      # proxy URL if any
        self.timeout = timeout                  # request timeout in seconds
        self.metadata = metadata or {}          # extra data middleware can attach
        self.attempt = 1                        # which retry attempt this is (starts at 1)

    def __repr__(self) -> str:
        return f"RequestContext(url={self.url}, attempt={self.attempt})"


class ResponseContext:
    """
    Holds the FetchResult plus any metadata middleware wants to attach.
    Middleware can inspect and modify this after the response arrives.
    """

    def __init__(self, result: FetchResult, request: RequestContext):
        self.result = result                    # the FetchResult from the fetcher
        self.request = request                  # the original RequestContext
        self.metadata: dict = {}                # middleware can attach extra info here

    @property
    def success(self) -> bool:
        """Convenience passthrough to the underlying FetchResult."""
        return self.result.success

    def __repr__(self) -> str:
        return f"ResponseContext(url={self.result.url}, success={self.success})"


# ── BaseMiddleware ────────────────────────────────────────────────────────────

class BaseMiddleware(ABC):
    """
    Abstract base class all middleware must inherit from.

    Each middleware implements two methods:
    - process_request()  → runs BEFORE the request is sent
    - process_response() → runs AFTER the response arrives

    The middleware chain works like this:
        request → MW1.process_request → MW2.process_request → Fetcher
        response ← MW1.process_response ← MW2.process_response ← Fetcher
    """

    def __init__(self, config: dict = None):
        """
        Args:
            config: optional per-middleware config overrides
        """
        self.config = config or {}
        self.enabled = True     # middleware can be toggled on/off without removing it
        log.debug("{} initialized", self.__class__.__name__)

    @abstractmethod
    async def process_request(self, context: RequestContext) -> RequestContext:
        """
        Called before a request is sent to the fetcher.
        Can modify the request context (add headers, inject proxy, etc.)
        or raise an exception to abort the request entirely.

        Args:
            context: the outgoing RequestContext

        Returns:
            modified RequestContext (or original if no changes needed)
        """
        ...

    @abstractmethod
    async def process_response(self, context: ResponseContext) -> ResponseContext:
        """
        Called after a response is received from the fetcher.
        Can inspect the result, log it, trigger a retry, or modify the data.

        Args:
            context: the ResponseContext wrapping the FetchResult

        Returns:
            modified ResponseContext (or original if no changes needed)
        """
        ...

    def disable(self) -> None:
        """Disables this middleware — process_request/response become pass-throughs."""
        self.enabled = False
        log.debug("{} disabled", self.__class__.__name__)

    def enable(self) -> None:
        """Re-enables this middleware after it was disabled."""
        self.enabled = True
        log.debug("{} enabled", self.__class__.__name__)

    def __repr__(self) -> str:
        status = "enabled" if self.enabled else "disabled"
        return f"{self.__class__.__name__}({status})"


# ── MiddlewareChain ───────────────────────────────────────────────────────────

class MiddlewareChain:
    """
    Manages an ordered list of middleware and runs them in sequence.

    This is what the spider uses — instead of calling each middleware
    individually, it hands the chain a request and gets back a response
    after all middleware have processed it.

    Usage:
        chain = MiddlewareChain([
            LoggingMiddleware(),
            ProxyMiddleware(),
            RetryMiddleware(),
        ])
        response = await chain.process(request_context, fetch_fn)
    """

    def __init__(self, middlewares: list[BaseMiddleware] = None):
        """
        Args:
            middlewares: ordered list of middleware instances.
                         Order matters — they run left to right on requests,
                         right to left on responses (like a stack).
        """
        self.middlewares = middlewares or []
        log.debug("MiddlewareChain initialized with {} middleware(s)",
                  len(self.middlewares))

    def add(self, middleware: BaseMiddleware) -> "MiddlewareChain":
        """
        Adds a middleware to the end of the chain.
        Returns self so calls can be chained:
            chain.add(LoggingMiddleware()).add(ProxyMiddleware())
        """
        self.middlewares.append(middleware)
        log.debug("Added {} to middleware chain", middleware.__class__.__name__)
        return self

    async def process(
        self,
        context: RequestContext,
        fetch_fn: Callable[[RequestContext], Awaitable[FetchResult]],
    ) -> ResponseContext:
        """
        Runs the request through all middleware, calls the fetcher,
        then runs the response back through all middleware in reverse.

        Args:
            context:  the outgoing RequestContext
            fetch_fn: the actual fetch function (from the fetcher layer)
                      signature: async def fetch_fn(ctx: RequestContext) → FetchResult

        Returns:
            ResponseContext after all middleware have processed it
        """
        # ── Request phase: forward through middleware (left to right) ─────────
        for mw in self.middlewares:
            if mw.enabled:
                log.debug("Request through: {}", mw.__class__.__name__)
                context = await mw.process_request(context)

        # ── Fetch: actually make the HTTP request ─────────────────────────────
        result = await fetch_fn(context)

        # ── Response phase: backward through middleware (right to left) ───────
        response = ResponseContext(result=result, request=context)

        for mw in reversed(self.middlewares):    # reversed() — same list, backwards
            if mw.enabled:
                log.debug("Response through: {}", mw.__class__.__name__)
                response = await mw.process_response(response)

        return response

    def __repr__(self) -> str:
        names = [mw.__class__.__name__ for mw in self.middlewares]
        return f"MiddlewareChain({' → '.join(names)})"
