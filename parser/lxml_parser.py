# ── parser/lxml_parser.py ─────────────────────────────────────────────────────
# lxml-based parser implementation.
#
# What is lxml?
#   A fast, C-based XML and HTML parsing library. It's significantly faster
#   than BS4's pure-Python parser and supports XPath — a powerful query
#   language for navigating HTML/XML trees.
#
# When to use LxmlParser vs BS4Parser:
#   BS4Parser  → most jobs, messy HTML, CSS selectors feel natural
#   LxmlParser → performance-critical jobs, large pages, XPath needed,
#                clean well-formed HTML
#
# XPath vs CSS Selectors:
#   CSS:   "div.product > span.price"      (what BS4 uses)
#   XPath: "//div[@class='product']/span[@class='price']"  (what lxml uses)
#   XPath is more powerful — can navigate upward in the tree, count elements,
#   check text content, handle complex conditions CSS can't express.
#
# Inherits from BaseParser.

from lxml import html as lxml_html     # lxml's HTML parsing module
from lxml import etree                 # lxml's core tree module
from urllib.parse import urljoin
from typing import Any, Optional
import re

from parser.base_parser import BaseParser, ParseResult
from utils.logger import log


class LxmlParser(BaseParser):
    """
    High-performance HTML parser using lxml with XPath support.

    Significantly faster than BS4 for large pages because lxml is
    written in C. Use this when parsing thousands of pages where
    parsing speed is a bottleneck.
    """

    def __init__(self, config: dict = None):
        super().__init__(config)
        log.debug("LxmlParser initialized")

    def _make_tree(self, html: str) -> lxml_html.HtmlElement:
        """
        Parses raw HTML into an lxml element tree.

        lxml_html.fromstring() returns the root element of the parsed tree.
        We can then run XPath queries against this root element.
        """
        try:
            # fromstring handles encoding detection and parser errors gracefully
            tree = lxml_html.fromstring(html)
            return tree
        except Exception as e:
            log.error("LxmlParser failed to parse HTML: {}", str(e))
            raise

    def parse(self, html: str, url: str = "") -> ParseResult:
        """
        Parse raw HTML and return a ParseResult with basic page metadata.

        Like BS4Parser, this base implementation extracts general metadata.
        In a real job you subclass LxmlParser and override parse() with
        XPath expressions for the specific data you need.

        Example subclass:
            class ProductParser(LxmlParser):
                def parse(self, html, url=""):
                    tree = self._make_tree(html)
                    return ParseResult(url=url, data=[{
                        "title": self.xpath_text(tree, "//h1[@class='title']"),
                        "price": self.xpath_text(tree, "//span[@class='price']"),
                    }])
        """
        if not html:
            return self.make_error_result(url, ValueError("Empty HTML"))

        try:
            tree = self._make_tree(html)

            # XPath to get the page title
            # //title/text() means: find any <title> tag anywhere, get its text
            title_nodes = tree.xpath("//title/text()")
            title = title_nodes[0].strip() if title_nodes else ""

            # Count paragraphs and links using XPath
            # //p counts all <p> tags anywhere in the document
            paragraph_count = len(tree.xpath("//p"))
            link_count = len(tree.xpath("//a[@href]"))

            data = [{
                "url": url,
                "title": title,
                "paragraph_count": paragraph_count,
                "link_count": link_count,
            }]

            log.debug("LxmlParser parsed: {} — title='{}'", url, title)

            return ParseResult(
                url=url,
                data=data,
                metadata={
                    "parser": "lxml",
                    "element_count": len(tree.xpath("//*")),
                }
            )

        except Exception as e:
            return self.make_error_result(url, e)

    def extract_links(self, html: str, base_url: str = "") -> list[str]:
        """
        Extracts all hyperlinks using XPath.
        lxml has a built-in method make_links_absolute() but we use
        XPath here for consistency and control.

        Args:
            html:     raw HTML string
            base_url: used to resolve relative links

        Returns:
            list of absolute URL strings
        """
        tree = self._make_tree(html)

        # XPath: find all <a> elements that have an href attribute
        # @href means "the href attribute exists"
        # //@href means "get the value of the href attribute"
        hrefs = tree.xpath("//a[@href]/@href")

        links = []
        for href in hrefs:
            href = href.strip()

            # Skip non-navigable links
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue

            # Resolve relative URLs
            if base_url:
                href = urljoin(base_url, href)

            if href.startswith(("http://", "https://")):
                links.append(href)

        # Deduplicate preserving order
        seen = set()
        unique_links = []
        for link in links:
            if link not in seen:
                seen.add(link)
                unique_links.append(link)

        log.debug("LxmlParser extracted {} links from {}", len(unique_links), base_url)
        return unique_links

    def extract_text(self, html: str) -> str:
        """
        Strips all HTML tags and returns clean plain text.
        lxml's text_content() method is very efficient for this.

        Args:
            html: raw HTML string

        Returns:
            clean plain text with tags removed
        """
        tree = self._make_tree(html)

        # Remove script and style elements and their content
        # etree.strip_elements removes tags AND content
        etree.strip_elements(tree, "script", "style", "head", "meta", "noscript")

        # text_content() is lxml's built-in method to get all text
        # It's equivalent to getting all text nodes recursively
        text = tree.text_content()

        # Collapse whitespace
        text = re.sub(r"\s+", " ", text).strip()
        return text

    # ── XPath helper methods for use in custom spiders ────────────────────────

    def xpath_text(
        self,
        tree: lxml_html.HtmlElement,
        xpath: str,
        fallback: str = "",
        index: int = 0,
    ) -> str:
        """
        Runs an XPath expression and returns the text of the first match.

        Example:
            title = parser.xpath_text(tree, "//h1[@class='title']/text()")
            price = parser.xpath_text(tree, "//span[@class='price']/text()")

        Args:
            tree:     the parsed lxml tree
            xpath:    XPath expression — should end in /text() for text nodes
            fallback: value to return if no match found
            index:    which result to return if multiple matches (default: first)
        """
        return self.safe_extract(
            lambda: tree.xpath(xpath)[index].strip(),
            fallback=fallback,
        )

    def xpath_all_text(
        self,
        tree: lxml_html.HtmlElement,
        xpath: str,
    ) -> list[str]:
        """
        Runs an XPath expression and returns text from ALL matches.

        Example:
            prices = parser.xpath_all_text(tree, "//span[@class='price']/text()")
            # → ["$9.99", "$14.99", "$7.49"]
        """
        return self.safe_extract(
            lambda: [t.strip() for t in tree.xpath(xpath) if t.strip()],
            fallback=[],
        )

    def xpath_attr(
        self,
        tree: lxml_html.HtmlElement,
        xpath: str,
        fallback: str = "",
    ) -> str:
        """
        Runs an XPath expression that returns an attribute value.
        XPath for attributes ends with /@attribute_name.

        Example:
            img_url = parser.xpath_attr(tree, "//img[@class='cover']/@src")
            next_url = parser.xpath_attr(tree, "//a[@class='next']/@href")
        """
        return self.safe_extract(
            lambda: tree.xpath(xpath)[0].strip(),
            fallback=fallback,
        )

    def xpath_all_attr(
        self,
        tree: lxml_html.HtmlElement,
        xpath: str,
    ) -> list[str]:
        """
        Returns an attribute value from ALL matching elements.

        Example:
            all_images = parser.xpath_all_attr(tree, "//img/@src")
        """
        return self.safe_extract(
            lambda: [v.strip() for v in tree.xpath(xpath) if v.strip()],
            fallback=[],
        )

    def xpath_exists(
        self,
        tree: lxml_html.HtmlElement,
        xpath: str,
    ) -> bool:
        """
        Returns True if any element matches the XPath expression.
        Useful for checking if a page has a specific element before extracting.

        Example:
            has_next_page = parser.xpath_exists(tree, "//a[@class='next']")
            is_product_page = parser.xpath_exists(tree, "//div[@class='product']")
        """
        return self.safe_extract(
            lambda: len(tree.xpath(xpath)) > 0,
            fallback=False,
        )

    def xpath_table(
        self,
        tree: lxml_html.HtmlElement,
        xpath: str = "//table",
    ) -> list[dict]:
        """
        Extracts a table as a list of dicts using XPath.
        Same output format as BS4Parser.get_table_data().

        Returns:
            [{"Header1": "value1", "Header2": "value2"}, ...]
        """
        def _extract():
            tables = tree.xpath(xpath)
            if not tables:
                return []

            table = tables[0]   # take first matching table
            rows = table.xpath(".//tr")
            if not rows:
                return []

            # Extract headers from first row
            headers = [
                th.text_content().strip()
                for th in rows[0].xpath(".//th|.//td")
            ]

            data = []
            for row in rows[1:]:
                cells = [td.text_content().strip() for td in row.xpath(".//td|.//th")]
                if cells:
                    data.append(dict(zip(headers, cells)))

            return data

        return self.safe_extract(_extract, fallback=[])

    def make_tree(self, html: str) -> lxml_html.HtmlElement:
        """
        Public access to _make_tree() for use in custom spiders.

        Usage in a spider:
            tree = parser.make_tree(result.html)
            items = tree.xpath("//div[@class='product']")
        """
        return self._make_tree(html)
