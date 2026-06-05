# ── parser/base_parser.py ─────────────────────────────────────────────────────
# Abstract base class for all parsers in the scraper skeleton.
#
# What does a parser do?
#   Takes raw HTML from the fetcher and extracts structured data from it.
#   Input:  raw HTML string  (e.g. "<html><h1>Book Title</h1><p>$9.99</p>")
#   Output: dict or list     (e.g. {"title": "Book Title", "price": "$9.99"})
#
# Parsers that will inherit from this (Day 6):
#   - BS4Parser    (BeautifulSoup4 — easy, flexible, beginner friendly)
#   - LxmlParser   (lxml — fast C-based, great for large pages)

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Any
from utils.logger import log


# ── ParseResult ───────────────────────────────────────────────────────────────

@dataclass
class ParseResult:
    """
    Standardized container for parsed data.
    Every parser returns a ParseResult regardless of implementation.

    Fields:
        url:     the source URL this data came from (for traceability)
        data:    the extracted data — list of dicts for multiple items
                 (e.g. list of products), single dict for one item
        errors:  any fields that failed to parse (non-fatal — we keep going)
        metadata: extra parser info (which selectors matched, how many items...)
    """
    url: str                                        # source URL for traceability
    data: list[dict] = field(default_factory=list)  # extracted items
    errors: list[str] = field(default_factory=list) # non-fatal parse errors
    metadata: dict = field(default_factory=dict)    # extra parser info

    @property
    def success(self) -> bool:
        """True if at least one item was extracted with no fatal errors."""
        return len(self.data) > 0

    @property
    def item_count(self) -> int:
        """How many items were extracted."""
        return len(self.data)

    def __str__(self) -> str:
        return f"ParseResult[{self.item_count} items] from {self.url}"


# ── BaseParser ────────────────────────────────────────────────────────────────

class BaseParser(ABC):
    """
    Abstract base class all parsers must inherit from.

    The spider calls parser.parse(html, url) every time.
    Whether it's BS4 or lxml underneath doesn't matter to the spider.
    """

    def __init__(self, config: dict = None):
        """
        Args:
            config: optional per-instance config overrides
                    e.g. {"encoding": "utf-8", "strict": False}
        """
        self.config = config or {}
        log.debug("{} initialized", self.__class__.__name__)

    @abstractmethod
    def parse(self, html: str, url: str = "") -> ParseResult:
        """
        Parse raw HTML and return a ParseResult containing extracted data.

        Args:
            html: raw HTML string from the fetcher
            url:  source URL — stored in ParseResult for traceability

        Returns:
            ParseResult with extracted data and any non-fatal errors
        """
        ...

    @abstractmethod
    def extract_links(self, html: str, base_url: str = "") -> list[str]:
        """
        Extract all hyperlinks from the HTML.
        Used by the spider to discover new URLs to scrape (crawling).

        Args:
            html:     raw HTML string
            base_url: used to resolve relative links to absolute URLs

        Returns:
            list of absolute URL strings
        """
        ...

    @abstractmethod
    def extract_text(self, html: str) -> str:
        """
        Strip all HTML tags and return plain text content only.
        Useful for text-heavy scrapes where you don't need structure.

        Args:
            html: raw HTML string

        Returns:
            plain text string with tags removed
        """
        ...

    def safe_extract(self, extractor_fn, fallback: Any = None) -> Any:
        """
        Wraps any extraction call in a try/except so a single failed
        field doesn't crash the entire parse operation.

        Usage inside a concrete parser:
            title = self.safe_extract(lambda: soup.find("h1").text, fallback="")

        Args:
            extractor_fn: a callable (usually a lambda) that does the extraction
            fallback:     value to return if extraction fails

        Returns:
            extracted value, or fallback if an exception occurred
        """
        try:
            return extractor_fn()
        except Exception as e:
            # Log at debug level — this is non-fatal, we keep going
            log.debug("{} safe_extract fallback: {}", self.__class__.__name__, str(e))
            return fallback

    def make_error_result(self, url: str, error: Exception) -> ParseResult:
        """
        Builds a failed ParseResult from an exception.
        Used when parsing fails so badly we can't extract anything at all.
        """
        log.error("{} failed for {}: {}", self.__class__.__name__, url, str(error))
        return ParseResult(
            url=url,
            data=[],
            errors=[str(error)],
        )

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(config={self.config})"
