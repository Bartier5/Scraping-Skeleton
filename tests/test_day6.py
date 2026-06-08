# ── tests/test_day6.py ────────────────────────────────────────────────────────
# Isolation tests for Day 6: BS4Parser and LxmlParser.
# Uses real HTML strings — no network calls needed.
#
# Run with: pytest tests/test_day6.py -v

import pytest

# ── Shared test HTML ──────────────────────────────────────────────────────────
# Realistic HTML that both parsers will work against

SIMPLE_HTML = """
<!DOCTYPE html>
<html>
<head><title>Test Page</title></head>
<body>
    <h1 class="main-title">Hello World</h1>
    <p class="intro">First paragraph.</p>
    <p class="content">Second paragraph.</p>
    <a href="/page-2">Next Page</a>
    <a href="https://external.com/page">External Link</a>
    <a href="mailto:test@test.com">Email</a>
    <a href="#anchor">Anchor</a>
    <span class="price">$9.99</span>
    <span class="price">$14.99</span>
    <img class="cover" src="/images/book.jpg" alt="Book Cover"/>
</body>
</html>
"""

TABLE_HTML = """
<html><body>
<table>
    <tr><th>Title</th><th>Price</th><th>Stock</th></tr>
    <tr><td>Book A</td><td>$9.99</td><td>In Stock</td></tr>
    <tr><td>Book B</td><td>$14.99</td><td>Out of Stock</td></tr>
    <tr><td>Book C</td><td>$7.49</td><td>In Stock</td></tr>
</table>
</body></html>
"""

SCRIPT_HTML = """
<html>
<head>
    <script>var x = 1; alert('test');</script>
    <style>body { color: red; }</style>
</head>
<body>
    <p>Real content here.</p>
    <script>console.log('another script');</script>
</body>
</html>
"""

BASE_URL = "https://books.toscrape.com"


# ── BS4Parser Tests ───────────────────────────────────────────────────────────

class TestBS4ParserInit:
    """Tests for BS4Parser initialization."""

    def test_initializes_with_default_backend(self):
        from parser.bs4_parser import BS4Parser
        parser = BS4Parser()
        assert parser._backend == "lxml"

    def test_initializes_with_custom_backend(self):
        from parser.bs4_parser import BS4Parser
        parser = BS4Parser(backend="html.parser")
        assert parser._backend == "html.parser"


class TestBS4ParserParse:
    """Tests for BS4Parser.parse()."""

    def test_returns_parse_result(self):
        from parser.bs4_parser import BS4Parser
        from parser.base_parser import ParseResult
        parser = BS4Parser()
        result = parser.parse(SIMPLE_HTML, url=BASE_URL)
        assert isinstance(result, ParseResult)

    def test_extracts_title(self):
        from parser.bs4_parser import BS4Parser
        parser = BS4Parser()
        result = parser.parse(SIMPLE_HTML, url=BASE_URL)
        assert result.data[0]["title"] == "Test Page"

    def test_counts_paragraphs(self):
        from parser.bs4_parser import BS4Parser
        parser = BS4Parser()
        result = parser.parse(SIMPLE_HTML, url=BASE_URL)
        assert result.data[0]["paragraph_count"] == 2

    def test_counts_links(self):
        from parser.bs4_parser import BS4Parser
        parser = BS4Parser()
        result = parser.parse(SIMPLE_HTML, url=BASE_URL)
        # 4 <a> tags total (next, external, mailto, anchor)
        assert result.data[0]["link_count"] == 4

    def test_success_with_valid_html(self):
        from parser.bs4_parser import BS4Parser
        parser = BS4Parser()
        result = parser.parse(SIMPLE_HTML, url=BASE_URL)
        assert result.success is True

    def test_failure_with_empty_html(self):
        from parser.bs4_parser import BS4Parser
        parser = BS4Parser()
        result = parser.parse("", url=BASE_URL)
        assert result.success is False
        assert len(result.errors) > 0

    def test_stores_source_url(self):
        from parser.bs4_parser import BS4Parser
        parser = BS4Parser()
        result = parser.parse(SIMPLE_HTML, url=BASE_URL)
        assert result.url == BASE_URL

    def test_metadata_contains_parser_info(self):
        from parser.bs4_parser import BS4Parser
        parser = BS4Parser()
        result = parser.parse(SIMPLE_HTML, url=BASE_URL)
        assert result.metadata["parser"] == "bs4"
        assert "element_count" in result.metadata


class TestBS4ParserExtractLinks:
    """Tests for BS4Parser.extract_links()."""

    def test_extracts_http_links(self):
        from parser.bs4_parser import BS4Parser
        parser = BS4Parser()
        links = parser.extract_links(SIMPLE_HTML, base_url=BASE_URL)
        assert "https://external.com/page" in links

    def test_resolves_relative_links(self):
        from parser.bs4_parser import BS4Parser
        parser = BS4Parser()
        links = parser.extract_links(SIMPLE_HTML, base_url=BASE_URL)
        assert f"{BASE_URL}/page-2" in links

    def test_excludes_mailto_links(self):
        from parser.bs4_parser import BS4Parser
        parser = BS4Parser()
        links = parser.extract_links(SIMPLE_HTML, base_url=BASE_URL)
        assert not any("mailto:" in link for link in links)

    def test_excludes_anchor_links(self):
        from parser.bs4_parser import BS4Parser
        parser = BS4Parser()
        links = parser.extract_links(SIMPLE_HTML, base_url=BASE_URL)
        assert not any(link.endswith("#anchor") for link in links)

    def test_deduplicates_links(self):
        from parser.bs4_parser import BS4Parser
        dup_html = """
        <html><body>
            <a href="/page">Link</a>
            <a href="/page">Duplicate</a>
            <a href="/page">Triple</a>
        </body></html>
        """
        parser = BS4Parser()
        links = parser.extract_links(dup_html, base_url=BASE_URL)
        assert len(links) == 1

    def test_returns_list(self):
        from parser.bs4_parser import BS4Parser
        parser = BS4Parser()
        result = parser.extract_links(SIMPLE_HTML)
        assert isinstance(result, list)


class TestBS4ParserExtractText:
    """Tests for BS4Parser.extract_text()."""

    def test_removes_html_tags(self):
        from parser.bs4_parser import BS4Parser
        parser = BS4Parser()
        text = parser.extract_text(SIMPLE_HTML)
        assert "<" not in text
        assert ">" not in text

    def test_removes_script_content(self):
        from parser.bs4_parser import BS4Parser
        parser = BS4Parser()
        text = parser.extract_text(SCRIPT_HTML)
        assert "var x = 1" not in text
        assert "console.log" not in text

    def test_removes_style_content(self):
        from parser.bs4_parser import BS4Parser
        parser = BS4Parser()
        text = parser.extract_text(SCRIPT_HTML)
        assert "color: red" not in text

    def test_keeps_real_content(self):
        from parser.bs4_parser import BS4Parser
        parser = BS4Parser()
        text = parser.extract_text(SCRIPT_HTML)
        assert "Real content here" in text

    def test_returns_string(self):
        from parser.bs4_parser import BS4Parser
        parser = BS4Parser()
        result = parser.extract_text(SIMPLE_HTML)
        assert isinstance(result, str)


class TestBS4ParserHelpers:
    """Tests for BS4Parser helper methods."""

    def test_get_text_css_selector(self):
        from parser.bs4_parser import BS4Parser
        parser = BS4Parser()
        soup = parser.make_soup(SIMPLE_HTML)
        text = parser.get_text(soup, "h1.main-title")
        assert text == "Hello World"

    def test_get_text_fallback_on_missing(self):
        from parser.bs4_parser import BS4Parser
        parser = BS4Parser()
        soup = parser.make_soup(SIMPLE_HTML)
        text = parser.get_text(soup, "div.nonexistent", fallback="missing")
        assert text == "missing"

    def test_get_attr(self):
        from parser.bs4_parser import BS4Parser
        parser = BS4Parser()
        soup = parser.make_soup(SIMPLE_HTML)
        src = parser.get_attr(soup, "img.cover", "src")
        assert src == "/images/book.jpg"

    def test_get_all_text(self):
        from parser.bs4_parser import BS4Parser
        parser = BS4Parser()
        soup = parser.make_soup(SIMPLE_HTML)
        prices = parser.get_all_text(soup, "span.price")
        assert "$9.99" in prices
        assert "$14.99" in prices
        assert len(prices) == 2

    def test_get_all_attr(self):
        from parser.bs4_parser import BS4Parser
        parser = BS4Parser()
        soup = parser.make_soup(SIMPLE_HTML)
        srcs = parser.get_all_attr(soup, "img", "src")
        assert "/images/book.jpg" in srcs

    def test_get_table_data(self):
        from parser.bs4_parser import BS4Parser
        parser = BS4Parser()
        soup = parser.make_soup(TABLE_HTML)
        rows = parser.get_table_data(soup)
        assert len(rows) == 3
        assert rows[0]["Title"] == "Book A"
        assert rows[0]["Price"] == "$9.99"
        assert rows[1]["Title"] == "Book B"

    def test_make_soup_returns_object(self):
        from parser.bs4_parser import BS4Parser
        from bs4 import BeautifulSoup
        parser = BS4Parser()
        soup = parser.make_soup(SIMPLE_HTML)
        assert isinstance(soup, BeautifulSoup)


# ── LxmlParser Tests ──────────────────────────────────────────────────────────

class TestLxmlParserInit:
    """Tests for LxmlParser initialization."""

    def test_initializes(self):
        from parser.lxml_parser import LxmlParser
        parser = LxmlParser()
        assert parser is not None


class TestLxmlParserParse:
    """Tests for LxmlParser.parse()."""

    def test_returns_parse_result(self):
        from parser.lxml_parser import LxmlParser
        from parser.base_parser import ParseResult
        parser = LxmlParser()
        result = parser.parse(SIMPLE_HTML, url=BASE_URL)
        assert isinstance(result, ParseResult)

    def test_extracts_title(self):
        from parser.lxml_parser import LxmlParser
        parser = LxmlParser()
        result = parser.parse(SIMPLE_HTML, url=BASE_URL)
        assert result.data[0]["title"] == "Test Page"

    def test_counts_paragraphs(self):
        from parser.lxml_parser import LxmlParser
        parser = LxmlParser()
        result = parser.parse(SIMPLE_HTML, url=BASE_URL)
        assert result.data[0]["paragraph_count"] == 2

    def test_success_with_valid_html(self):
        from parser.lxml_parser import LxmlParser
        parser = LxmlParser()
        result = parser.parse(SIMPLE_HTML, url=BASE_URL)
        assert result.success is True

    def test_failure_with_empty_html(self):
        from parser.lxml_parser import LxmlParser
        parser = LxmlParser()
        result = parser.parse("", url=BASE_URL)
        assert result.success is False

    def test_metadata_contains_parser_info(self):
        from parser.lxml_parser import LxmlParser
        parser = LxmlParser()
        result = parser.parse(SIMPLE_HTML, url=BASE_URL)
        assert result.metadata["parser"] == "lxml"


class TestLxmlParserExtractLinks:
    """Tests for LxmlParser.extract_links()."""

    def test_extracts_http_links(self):
        from parser.lxml_parser import LxmlParser
        parser = LxmlParser()
        links = parser.extract_links(SIMPLE_HTML, base_url=BASE_URL)
        assert "https://external.com/page" in links

    def test_resolves_relative_links(self):
        from parser.lxml_parser import LxmlParser
        parser = LxmlParser()
        links = parser.extract_links(SIMPLE_HTML, base_url=BASE_URL)
        assert f"{BASE_URL}/page-2" in links

    def test_excludes_mailto(self):
        from parser.lxml_parser import LxmlParser
        parser = LxmlParser()
        links = parser.extract_links(SIMPLE_HTML, base_url=BASE_URL)
        assert not any("mailto:" in link for link in links)

    def test_returns_list(self):
        from parser.lxml_parser import LxmlParser
        parser = LxmlParser()
        result = parser.extract_links(SIMPLE_HTML)
        assert isinstance(result, list)


class TestLxmlParserExtractText:
    """Tests for LxmlParser.extract_text()."""

    def test_removes_tags(self):
        from parser.lxml_parser import LxmlParser
        parser = LxmlParser()
        text = parser.extract_text(SIMPLE_HTML)
        assert "<" not in text
        assert ">" not in text

    def test_removes_script_content(self):
        from parser.lxml_parser import LxmlParser
        parser = LxmlParser()
        text = parser.extract_text(SCRIPT_HTML)
        assert "var x = 1" not in text

    def test_keeps_real_content(self):
        from parser.lxml_parser import LxmlParser
        parser = LxmlParser()
        text = parser.extract_text(SCRIPT_HTML)
        assert "Real content here" in text

    def test_returns_string(self):
        from parser.lxml_parser import LxmlParser
        parser = LxmlParser()
        result = parser.extract_text(SIMPLE_HTML)
        assert isinstance(result, str)


class TestLxmlParserHelpers:
    """Tests for LxmlParser XPath helper methods."""

    def test_xpath_text(self):
        from parser.lxml_parser import LxmlParser
        parser = LxmlParser()
        tree = parser.make_tree(SIMPLE_HTML)
        title = parser.xpath_text(tree, "//h1/text()")
        assert title == "Hello World"

    def test_xpath_text_fallback(self):
        from parser.lxml_parser import LxmlParser
        parser = LxmlParser()
        tree = parser.make_tree(SIMPLE_HTML)
        result = parser.xpath_text(tree, "//div[@class='nonexistent']/text()", fallback="missing")
        assert result == "missing"

    def test_xpath_all_text(self):
        from parser.lxml_parser import LxmlParser
        parser = LxmlParser()
        tree = parser.make_tree(SIMPLE_HTML)
        prices = parser.xpath_all_text(tree, "//span[@class='price']/text()")
        assert "$9.99" in prices
        assert "$14.99" in prices

    def test_xpath_attr(self):
        from parser.lxml_parser import LxmlParser
        parser = LxmlParser()
        tree = parser.make_tree(SIMPLE_HTML)
        src = parser.xpath_attr(tree, "//img[@class='cover']/@src")
        assert src == "/images/book.jpg"

    def test_xpath_exists_true(self):
        from parser.lxml_parser import LxmlParser
        parser = LxmlParser()
        tree = parser.make_tree(SIMPLE_HTML)
        assert parser.xpath_exists(tree, "//h1") is True

    def test_xpath_exists_false(self):
        from parser.lxml_parser import LxmlParser
        parser = LxmlParser()
        tree = parser.make_tree(SIMPLE_HTML)
        assert parser.xpath_exists(tree, "//div[@class='nonexistent']") is False

    def test_xpath_table(self):
        from parser.lxml_parser import LxmlParser
        parser = LxmlParser()
        tree = parser.make_tree(TABLE_HTML)
        rows = parser.xpath_table(tree)
        assert len(rows) == 3
        assert rows[0]["Title"] == "Book A"
        assert rows[0]["Price"] == "$9.99"

    def test_make_tree_returns_element(self):
        from parser.lxml_parser import LxmlParser
        from lxml import html as lxml_html
        parser = LxmlParser()
        tree = parser.make_tree(SIMPLE_HTML)
        assert isinstance(tree, lxml_html.HtmlElement)


# ── Cross-parser consistency tests ────────────────────────────────────────────

class TestParserConsistency:
    """
    Tests that BS4Parser and LxmlParser produce consistent results.
    Both should agree on the same HTML — they use different engines
    but must produce equivalent output for the spider to be swappable.
    """

    def test_both_extract_same_title(self):
        from parser.bs4_parser import BS4Parser
        from parser.lxml_parser import LxmlParser

        bs4 = BS4Parser()
        lxml = LxmlParser()

        bs4_result = bs4.parse(SIMPLE_HTML, url=BASE_URL)
        lxml_result = lxml.parse(SIMPLE_HTML, url=BASE_URL)

        assert bs4_result.data[0]["title"] == lxml_result.data[0]["title"]

    def test_both_extract_same_paragraph_count(self):
        from parser.bs4_parser import BS4Parser
        from parser.lxml_parser import LxmlParser

        bs4 = BS4Parser()
        lxml = LxmlParser()

        bs4_result = bs4.parse(SIMPLE_HTML, url=BASE_URL)
        lxml_result = lxml.parse(SIMPLE_HTML, url=BASE_URL)

        assert bs4_result.data[0]["paragraph_count"] == lxml_result.data[0]["paragraph_count"]

    def test_both_exclude_scripts_from_text(self):
        from parser.bs4_parser import BS4Parser
        from parser.lxml_parser import LxmlParser

        bs4 = BS4Parser()
        lxml = LxmlParser()

        bs4_text = bs4.extract_text(SCRIPT_HTML)
        lxml_text = lxml.extract_text(SCRIPT_HTML)

        assert "var x = 1" not in bs4_text
        assert "var x = 1" not in lxml_text

    def test_both_extract_external_links(self):
        from parser.bs4_parser import BS4Parser
        from parser.lxml_parser import LxmlParser

        bs4 = BS4Parser()
        lxml = LxmlParser()

        bs4_links = bs4.extract_links(SIMPLE_HTML, base_url=BASE_URL)
        lxml_links = lxml.extract_links(SIMPLE_HTML, base_url=BASE_URL)

        assert "https://external.com/page" in bs4_links
        assert "https://external.com/page" in lxml_links
