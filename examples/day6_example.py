# ── examples/day6_example.py ──────────────────────────────────────────────────
# Day 6 mini example — BS4Parser and LxmlParser on real scraped HTML.
# Fetches real pages then parses them with both parsers side by side.
#
# Run with: python examples/day6_example.py

import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from utils.logger import log
from utils.helpers import ensure_dir
from fetcher.http_fetcher import HttpFetcher
from parser.bs4_parser import BS4Parser
from parser.lxml_parser import LxmlParser


def main():
    ensure_dir("logs")
    ensure_dir("data")

    log.info("=" * 60)
    log.info("Day 6 — BS4Parser + LxmlParser Demo")
    log.info("=" * 60)

    # ── Fetch real HTML to parse ──────────────────────────────────────────────
    log.info("Fetching HTML from books.toscrape.com...")

    with HttpFetcher() as fetcher:
        books_result = fetcher.fetch("https://books.toscrape.com/catalogue/page-1.html")
        quotes_result = fetcher.fetch("https://quotes.toscrape.com/page/1/")

    if not books_result.success or not quotes_result.success:
        log.error("Failed to fetch pages — check network connection")
        return

    log.info("Fetched {} chars from books site", len(books_result.html))
    log.info("Fetched {} chars from quotes site", len(quotes_result.html))

    bs4 = BS4Parser()
    lxml = LxmlParser()

    # ── 1. Basic parse — title, paragraphs, links ─────────────────────────────
    log.info("1. Basic parse — title and metadata:")

    bs4_result = bs4.parse(books_result.html, url=books_result.url)
    lxml_result = lxml.parse(books_result.html, url=books_result.url)

    log.info("  BS4  → title='{}' paragraphs={} links={}",
             bs4_result.data[0]["title"],
             bs4_result.data[0]["paragraph_count"],
             bs4_result.data[0]["link_count"])

    log.info("  lxml → title='{}' paragraphs={} links={}",
             lxml_result.data[0]["title"],
             lxml_result.data[0]["paragraph_count"],
             lxml_result.data[0]["link_count"])

    log.info("  Titles match: {}", bs4_result.data[0]["title"] == lxml_result.data[0]["title"])

    # ── 2. Link extraction ────────────────────────────────────────────────────
    log.info("2. Link extraction from books catalogue:")

    bs4_links = bs4.extract_links(books_result.html, base_url="https://books.toscrape.com")
    lxml_links = lxml.extract_links(books_result.html, base_url="https://books.toscrape.com")

    log.info("  BS4  extracted {} links", len(bs4_links))
    log.info("  lxml extracted {} links", len(lxml_links))
    log.info("  First 3 links (BS4):")
    for link in bs4_links[:3]:
        log.info("    {}", link)

    # ── 3. Text extraction ────────────────────────────────────────────────────
    log.info("3. Plain text extraction:")

    bs4_text = bs4.extract_text(books_result.html)
    lxml_text = lxml.extract_text(books_result.html)

    log.info("  BS4  text length: {} chars", len(bs4_text))
    log.info("  lxml text length: {} chars", len(lxml_text))
    log.info("  BS4  first 100: {!r}", bs4_text[:100])

    # ── 4. BS4 helpers — CSS selector extraction ──────────────────────────────
    log.info("4. BS4 CSS selector helpers — scraping book data:")

    soup = bs4.make_soup(books_result.html)

    # Extract book titles using CSS selectors
    titles = bs4.get_all_text(soup, "h3 > a")
    prices = bs4.get_all_text(soup, "p.price_color")
    ratings = bs4.get_all_attr(soup, "p.star-rating", "class")

    log.info("  Books found: {}", len(titles))
    log.info("  Prices found: {}", len(prices))

    # Show first 5 books
    log.info("  First 5 books:")
    for i, (title, price) in enumerate(zip(titles[:5], prices[:5]), 1):
        log.info("    {}. {} — {}", i, title[:40], price)

    # ── 5. lxml helpers — XPath extraction ───────────────────────────────────
    log.info("5. lxml XPath helpers — scraping quotes:")

    tree = lxml.make_tree(quotes_result.html)

    # XPath to extract quote text and authors
    quote_texts = lxml.xpath_all_text(tree, "//span[@class='text']/text()")
    authors = lxml.xpath_all_text(tree, "//small[@class='author']/text()")
    has_next = lxml.xpath_exists(tree, "//li[@class='next']")

    log.info("  Quotes found: {}", len(quote_texts))
    log.info("  Authors found: {}", len(authors))
    log.info("  Has next page: {}", has_next)

    log.info("  First 3 quotes:")
    for i, (quote, author) in enumerate(zip(quote_texts[:3], authors[:3]), 1):
        log.info("    {}. {} — {}", i, quote[:60], author)

    # ── 6. Table extraction ───────────────────────────────────────────────────
    log.info("6. Table extraction — book detail page:")

    with HttpFetcher() as fetcher:
        # Books.toscrape.com product pages have a details table
        detail_result = fetcher.fetch(
            "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"
        )

    if detail_result.success:
        soup = bs4.make_soup(detail_result.html)
        table_data = bs4.get_table_data(soup, "table.table-striped")

        log.info("  Table rows extracted: {}", len(table_data))
        for row in table_data:
            # Each row is a dict — print first key/value pair
            for k, v in row.items():
                log.info("    {} → {}", k, v)

    # ── 7. safe_extract demo ──────────────────────────────────────────────────
    log.info("7. safe_extract — graceful failure handling:")

    soup = bs4.make_soup("<html><body><p>Simple page</p></body></html>")

    # This will succeed
    good = bs4.get_text(soup, "p", fallback="not found")
    log.info("  Found element: {!r}", good)

    # This will fail gracefully — no div.product on this page
    missing = bs4.get_text(soup, "div.product-price", fallback="price not found")
    log.info("  Missing element: {!r}", missing)

    # ── 8. Parser comparison summary ─────────────────────────────────────────
    log.info("8. Parser comparison:")
    log.info("  BS4Parser:  CSS selectors, forgiving, readable, slightly slower")
    log.info("  LxmlParser: XPath, strict, faster, more powerful queries")
    log.info("  Both return ParseResult — spider doesn't know which is active")

    log.info("=" * 60)
    log.success("Day 6 complete — BS4 and lxml parsers fully working")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
