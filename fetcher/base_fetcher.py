# ── fetcher/base_fetcher.py ───────────────────────────────────────────────────
# Abstract base class for all fetchers in the scraper skeleton.
#
# What is an abstract base class (ABC)?
#   It's a class that defines WHAT a fetcher must be able to do, without
#   specifying HOW it does it. Think of it as a contract or job description.
#   Any class that inherits from BaseFetcher must implement every method
#   marked with @abstractmethod — or Python will raise an error at runtime.
#
# Why do we need this?
#   Without a base class, every fetcher (requests, aiohttp, Playwright) would
#   have different method names and signatures. The spider would need to know
#   which fetcher it's using and call it differently each time.
#   With a base class, the spider always calls fetcher.fetch(url) regardless
#   of which fetcher is underneath. Swapping fetchers = zero spider changes.
#
# Fetchers that will inherit from this (Days 4 & 5):
#   - HttpFetcher      (requests — sync)
#   - AsyncFetcher     (aiohttp — async)
#   - BatchFetcher     (aiohttp + semaphore — async batch)
#   - BrowserFetcher   (Playwright — JS rendering)

from abc import ABC, abstractmethod     # ABC = Abstract Base Class machinery
from dataclasses import dataclass, field  # clean data container for responses
from typing import Optional             # type hint — value can be None
from utils.logger import log


# ── FetchResult ───────────────────────────────────────────────────────────────

@dataclass
class FetchResult:
    """
    A standardized container for the result of any fetch operation.
    Every fetcher — regardless of implementation — returns a FetchResult.
    This means the parser always receives the same object shape.

    @dataclass automatically generates __init__, __repr__, and __eq__
    so we don't have to write them manually.

    Fields:
        url:         the URL that was fetched
        status_code: HTTP response code (200=ok, 404=not found, 429=rate limited...)
        html:        raw HTML content of the page (empty string if failed)
        headers:     response headers dict (useful for cookies, content-type, etc.)
        error:       exception message if the fetch failed, None if successful
        metadata:    any extra data the fetcher wants to pass along (optional)
    """
    url: str                                    # the requested URL
    status_code: int = 0                        # 0 means request never completed
    html: str = ""                              # raw HTML body
    headers: dict = field(default_factory=dict) # response headers
    error: Optional[str] = None                 # error message if failed
    metadata: dict = field(default_factory=dict)# extra fetcher-specific data

    @property
    def success(self) -> bool:
        """
        Convenience property — True if the fetch was successful.
        A successful fetch has status 200-299 and no error message.

        Usage:
            result = fetcher.fetch(url)
            if result.success:
                parser.parse(result.html)
        """
        return 200 <= self.status_code < 300 and self.error is None

    @property
    def failed(self) -> bool:
        """Opposite of success — True if something went wrong."""
        return not self.success

    def __str__(self) -> str:
        """Human-readable summary for logging."""
        status = "OK" if self.success else "FAILED"
        return f"FetchResult[{status}] {self.url} (HTTP {self.status_code})"


# ── BaseFetcher ───────────────────────────────────────────────────────────────

class BaseFetcher(ABC):
    """
    Abstract base class that all fetchers must inherit from.

    Defines the interface (contract) every fetcher must implement.
    Concrete fetchers fill in the HOW, this class defines the WHAT.

    Inheriting from ABC means:
    - Any class that inherits BaseFetcher MUST implement all @abstractmethod methods
    - Trying to instantiate BaseFetcher directly raises TypeError
    - Python enforces the contract at class creation time, not just at call time
    """

    def __init__(self, config: dict = None):
        """
        Base constructor — stores optional config overrides.
        Concrete fetchers call super().__init__(config) to run this.

        Args:
            config: optional dict to override Config values for this fetcher instance
                    e.g. {"timeout": 60, "max_retries": 5}
        """
        self.config = config or {}          # store any per-instance config overrides
        log.debug("{} initialized", self.__class__.__name__)

    @abstractmethod
    def fetch(self, url: str, **kwargs) -> FetchResult:
        """
        Fetch a single URL and return a FetchResult.

        This is the core method every fetcher must implement.
        The sync version — used by HttpFetcher (requests).

        Args:
            url:    the URL to fetch
            **kwargs: optional per-request overrides (headers, timeout, proxy...)

        Returns:
            FetchResult with html, status_code, headers, and error if any
        """
        ...     # ... is valid Python — means "not implemented here, subclass handles it"

    @abstractmethod
    async def async_fetch(self, url: str, **kwargs) -> FetchResult:
        """
        Async version of fetch() — used by AsyncFetcher and BrowserFetcher.

        Marked abstractmethod so all fetchers must implement it even if they
        just call the sync version internally (for consistency).

        Args:
            url:    the URL to fetch
            **kwargs: optional per-request overrides

        Returns:
            FetchResult — same shape as sync fetch()
        """
        ...

    @abstractmethod
    async def fetch_many(self, urls: list[str], **kwargs) -> list[FetchResult]:
        """
        Fetch multiple URLs — used by BatchFetcher.
        Concrete implementations decide whether to use concurrency here.

        Args:
            urls:   list of URLs to fetch
            **kwargs: optional overrides applied to all requests

        Returns:
            list of FetchResult, one per URL, in the same order as input
        """
        ...

    def validate_url(self, url: str) -> bool:
        """
        Shared URL validation used by all fetchers before making a request.
        Not abstract — this implementation is inherited by all subclasses.

        Returns True if valid, logs warning and returns False if not.
        """
        from utils.helpers import is_valid_url
        if not is_valid_url(url):
            log.warning("{} received invalid URL: {}", self.__class__.__name__, url)
            return False
        return True

    def make_error_result(self, url: str, error: Exception, status_code: int = 0) -> FetchResult:
        """
        Builds a failed FetchResult from an exception.
        Shared helper so all fetchers handle errors consistently.

        Usage inside a fetcher:
            except Exception as e:
                return self.make_error_result(url, e)
        """
        log.error("{} failed for {}: {}", self.__class__.__name__, url, str(error))
        return FetchResult(
            url=url,
            status_code=status_code,
            error=str(error),           # convert exception to string for storage
        )

    def __repr__(self) -> str:
        """String representation for logging — shows which fetcher is active."""
        return f"{self.__class__.__name__}(config={self.config})"
