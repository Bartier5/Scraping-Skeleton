# ── parser/bs4_parser.py ──────────────────────────────────────────────────────
# BeautifulSoup4 parser implementation.
#
# What is BeautifulSoup4?
#   A Python library that parses HTML and lets you navigate, search, and
#   extract data from it using a simple, readable API.
#   It's the most popular HTML parser in Python scraping because it's
#   forgiving (handles messy real-world HTML), flexible, and easy to use.
#
# When to use BS4Parser vs LxmlParser:
#   BS4Parser  → most jobs, messy HTML, readability matters, CSS selectors
#   LxmlParser → performance-critical jobs, clean HTML, XPath needed
#
# How BS4 works:
#   BS4 takes raw HTML string → builds a tree of HTML elements → lets you
#   search that tree by tag name, CSS class, id, attributes, or CSS selectors.
#
# Inherits from BaseParser — implements all three required methods.

from bs4 import BeautifulSoup, Tag     # core BS4 classes
from bs4 import FeatureNotFound        # raised if lxml not installed as backend
from urllib.parse import urljoin       # combine base URL with relative links
from typing import Any, Optional

from parser.base_parser import BaseParser, ParseResult
from utils.logger import log


class BS4Parser(BaseParser):
    """
    HTML parser using BeautifulSoup4 with lxml as the backend engine.

    BS4 supports multiple backend parsers:
    - "lxml"         → fastest, requires lxml installed (recommended)
    - "html.parser"  → built-in Python parser, slower but no dependencies
    - "html5lib"     → most lenient, handles severely broken HTML

    We use lxml as default since we already have it installed,
    falling back to html.parser if lxml is unavailable.
    """

    def __init__(self, config: dict = None, backend: str = "lxml"):
        """
        Args:
            config:  optional config overrides
            backend: BS4 backend parser engine
                     "lxml" (default) → fastest, most reliable
                     "html.parser"    → pure Python fallback
        """
        super().__init__(config)
        self._backend = backend
        log.debug("BS4Parser initialized (backend={})", backend)

    def _make_soup(self, html: str) -> BeautifulSoup:
        """
        Creates a BeautifulSoup object from raw HTML.
        Falls back to html.parser if lxml is not available.

        BeautifulSoup(html, parser) builds the element tree we search.
        """
        try:
            return BeautifulSoup(html, self._backend)
        except FeatureNotFound:
            # lxml not installed — fall back to built-in parser
            log.warning("BS4Parser: lxml not available, using html.parser")
            return BeautifulSoup(html, "html.parser")

    def parse(self, html: str, url: str = "") -> ParseResult:
        """
        Parse raw HTML and return a ParseResult.

        This is the base implementation — it extracts the page title and
        basic metadata. In real scraping jobs you override this with a
        custom spider that calls the helper methods below to extract
        the specific data you need.

        For a real job you'd subclass BS4Parser and override parse():
            class ProductParser(BS4Parser):
                def parse(self, html, url=""):
                    soup = self._make_soup(html)
                    return ParseResult(url=url, data=[{
                        "title": self.get_text(soup, "h1.product-title"),
                        "price": self.get_text(soup, "span.price"),
                    }])

        Args:
            html: raw HTML string from the fetcher
            url:  source URL stored in ParseResult for traceability

        Returns:
            ParseResult with basic page metadata extracted
        """
        if not html:
            return self.make_error_result(url, ValueError("Empty HTML"))

        try:
            soup = self._make_soup(html)

            # Extract basic page metadata that's always present
            title = self.safe_extract(
                lambda: soup.find("title").get_text(strip=True),
                fallback=""
            )

            # Count paragraphs as a simple content indicator
            paragraphs = soup.find_all("p")
            links = soup.find_all("a", href=True)

            data = [{
                "url": url,
                "title": title,
                "paragraph_count": len(paragraphs),
                "link_count": len(links),
            }]

            log.debug("BS4Parser parsed: {} — title='{}'", url, title)

            return ParseResult(
                url=url,
                data=data,
                metadata={
                    "parser": "bs4",
                    "backend": self._backend,
                    "element_count": len(soup.find_all()),
                }
            )

        except Exception as e:
            return self.make_error_result(url, e)

    def extract_links(self, html: str, base_url: str = "") -> list[str]:
        """
        Extracts all hyperlinks from the HTML.
        Converts relative links to absolute using base_url.

        Args:
            html:     raw HTML string
            base_url: used to resolve relative links e.g. "/page-2" → full URL

        Returns:
            list of absolute URL strings — deduped and filtered to http/https only
        """
        soup = self._make_soup(html)
        links = []

        # find_all("a", href=True) gets all <a> tags that have an href attribute
        for tag in soup.find_all("a", href=True):
            href = tag["href"].strip()    # get the href value, strip whitespace

            # Skip empty hrefs, javascript:, mailto:, anchor links
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue

            # urljoin handles both absolute and relative URLs correctly
            # If href is already absolute: "https://example.com/page" → unchanged
            # If href is relative: "/page-2" + base → "https://example.com/page-2"
            if base_url:
                href = urljoin(base_url, href)

            # Only include http/https links
            if href.startswith(("http://", "https://")):
                links.append(href)

        # Deduplicate while preserving order
        seen = set()
        unique_links = []
        for link in links:
            if link not in seen:
                seen.add(link)
                unique_links.append(link)

        log.debug("BS4Parser extracted {} links from {}", len(unique_links), base_url)
        return unique_links

    def extract_text(self, html: str) -> str:
        """
        Strips all HTML tags and returns plain text content.
        Removes script and style content, collapses whitespace.

        Args:
            html: raw HTML string

        Returns:
            clean plain text string
        """
        soup = self._make_soup(html)

        # Remove script and style tags and their content entirely
        # We don't want JavaScript code or CSS in our plain text
        for tag in soup(["script", "style", "head", "meta", "noscript"]):
            tag.decompose()     # decompose() removes the tag AND its contents

        # get_text() extracts all remaining text
        # separator=" " puts a space between elements that were on separate lines
        # strip=True removes leading/trailing whitespace from each text chunk
        text = soup.get_text(separator=" ", strip=True)

        # Collapse multiple spaces into one
        import re
        text = re.sub(r"\s+", " ", text).strip()

        return text

    # ── Helper methods for use in custom spiders ──────────────────────────────
    # These make it easier to write clean extraction code in your spider.

    def get_text(
        self,
        soup: BeautifulSoup,
        selector: str,
        fallback: str = "",
    ) -> str:
        """
        Finds the first element matching a CSS selector and returns its text.
        Returns fallback if element not found.

        Example:
            title = parser.get_text(soup, "h1.product-title")
            price = parser.get_text(soup, "span.price", fallback="N/A")
        """
        return self.safe_extract(
            lambda: soup.select_one(selector).get_text(strip=True),
            fallback=fallback,
        )

    def get_attr(
        self,
        soup: BeautifulSoup,
        selector: str,
        attribute: str,
        fallback: str = "",
    ) -> str:
        """
        Finds the first element matching selector and returns an attribute value.

        Example:
            img_url = parser.get_attr(soup, "img.product-image", "src")
            link = parser.get_attr(soup, "a.next-page", "href")
        """
        return self.safe_extract(
            lambda: soup.select_one(selector)[attribute],
            fallback=fallback,
        )

    def get_all_text(
        self,
        soup: BeautifulSoup,
        selector: str,
    ) -> list[str]:
        """
        Returns text from ALL elements matching the CSS selector.

        Example:
            prices = parser.get_all_text(soup, "span.price")
            # → ["$9.99", "$14.99", "$7.49"]
        """
        return self.safe_extract(
            lambda: [el.get_text(strip=True) for el in soup.select(selector)],
            fallback=[],
        )

    def get_all_attr(
        self,
        soup: BeautifulSoup,
        selector: str,
        attribute: str,
    ) -> list[str]:
        """
        Returns an attribute value from ALL elements matching the selector.

        Example:
            image_urls = parser.get_all_attr(soup, "img.product-image", "src")
        """
        return self.safe_extract(
            lambda: [el[attribute] for el in soup.select(selector) if attribute in el.attrs],
            fallback=[],
        )

    def get_table_data(
        self,
        soup: BeautifulSoup,
        selector: str = "table",
    ) -> list[dict]:
        """
        Extracts a table as a list of dicts — each row becomes a dict
        with column headers as keys.

        Example HTML:
            <table>
              <tr><th>Name</th><th>Price</th></tr>
              <tr><td>Book A</td><td>$9.99</td></tr>
            </table>

        Returns:
            [{"Name": "Book A", "Price": "$9.99"}]
        """
        def _extract():
            table = soup.select_one(selector)
            if not table:
                return []

            rows = table.find_all("tr")
            if not rows:
                return []

            # First row is headers
            headers = [th.get_text(strip=True) for th in rows[0].find_all(["th", "td"])]

            data = []
            for row in rows[1:]:    # skip header row
                cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
                if cells:
                    # zip pairs headers with cell values — handles uneven rows gracefully
                    data.append(dict(zip(headers, cells)))

            return data

        return self.safe_extract(_extract, fallback=[])

    def make_soup(self, html: str) -> BeautifulSoup:
        """
        Public access to _make_soup() for use in custom spiders.

        Usage in a spider:
            soup = parser.make_soup(result.html)
            items = soup.select(".product-item")
        """
        return self._make_soup(html)
