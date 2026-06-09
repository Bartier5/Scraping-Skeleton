# ── examples/day8_example.py ──────────────────────────────────────────────────
# Day 8 mini example — full pipeline on real scraped data.
# Fetches books and quotes, runs them through cleaner → transformer → validator.
#
# Run with: python examples/day8_example.py

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.logger import log
from utils.helpers import ensure_dir
from fetcher.http_fetcher import HttpFetcher
from parser.bs4_parser import BS4Parser
from pipeline.cleaner import DataCleaner
from pipeline.transformer import DataTransformer
from pipeline.validator import DataValidator, BookSchema, QuoteSchema


def main():
    ensure_dir("logs")
    ensure_dir("data")

    log.info("=" * 60)
    log.info("Day 8 — Full Pipeline Demo")
    log.info("=" * 60)

    # ── Fetch and parse raw data ──────────────────────────────────────────────
    log.info("Fetching HTML...")
    with HttpFetcher() as fetcher:
        books_html = fetcher.fetch("https://books.toscrape.com/catalogue/page-1.html")
        quotes_html = fetcher.fetch("https://quotes.toscrape.com/page/1/")

    parser = BS4Parser()

    # ── 1. DataCleaner — normalize raw scraped data ───────────────────────────
    log.info("1. DataCleaner — normalizing raw scraped values:")

    dirty_items = [
        {
            "title": "  A Light in the Attic  \n",
            "price": "Â£51.77",
            "url": "  https://books.toscrape.com/catalogue/a-light_1000/  \n",
            "stock": None,
            "internal_id": "  1000  ",
        },
        {
            "title": "\tTipping the Velvet\t",
            "price": "Â£53.74",
            "url": "https://books.toscrape.com/catalogue/tipping_2/index.html",
            "stock": "In stock (22 available)",
            "internal_id": "  1001  ",
        },
    ]

    cleaner = DataCleaner()
    cleaned = cleaner.clean_items(dirty_items)

    log.info("  Before / After:")
    for dirty, clean in zip(dirty_items, cleaned):
        log.info("  title:  {!r} → {!r}", dirty["title"], clean["title"])
        log.info("  price:  {!r} → {!r}", dirty["price"], clean["price"])
        log.info("  url:    {!r:.50} → {!r:.50}", dirty["url"], clean["url"])
        log.info("  stock:  {!r} → {!r}", dirty["stock"], clean["stock"])

    # static helpers demo
    log.info("  extract_number('In stock (22)'): {}",
             DataCleaner.extract_number("In stock (22)"))
    log.info("  strip_html_tags('<b>Price:</b> $9.99'): {}",
             DataCleaner.strip_html_tags("<b>Price:</b> $9.99"))

    # ── 2. DataTransformer — reshape for storage ──────────────────────────────
    log.info("2. DataTransformer — reshaping for storage schema:")

    transformer = DataTransformer(
        field_map={
            "price": "price_raw",        # rename price before casting
            "internal_id": "source_id",  # rename internal fields
        },
        drop_fields=["source_id"],       # drop internal fields after rename
        type_casts={},
        computed={
            "price": lambda item: DataCleaner.extract_number(
                item.get("price_raw", "0") or "0"
            ),
        },
        add_metadata=True,
    )

    transformed = transformer.transform_items(cleaned)

    log.info("  Transformed fields: {}", list(transformed[0].keys()))
    for item in transformed:
        log.info("  title={!r} price={} scraped_at={}",
                 item.get("title"),
                 item.get("price"),
                 item.get("scraped_at", "")[:19])

    # ── 3. DataValidator — schema enforcement ─────────────────────────────────
    log.info("3. DataValidator — validating against BookSchema:")

    # Prep items properly for validation
    valid_items = [
        {"url": "https://books.toscrape.com/1", "title": "Book A", "price": 9.99},
        {"url": "https://books.toscrape.com/2", "title": "Book B", "price": 14.99},
        {"title": "No URL here"},          # invalid — missing required url
        {"url": "https://books.toscrape.com/4"},  # invalid — missing required title
    ]

    validator = DataValidator(schema=BookSchema, strict=False)
    batch = validator.validate_batch(valid_items)

    log.info("  {}", batch)
    log.info("  Valid items: {}", len(batch.valid_items))
    log.info("  Invalid items: {}", len(batch.invalid_items))
    for inv in batch.invalid_items:
        log.info("  ✗ Errors: {}", inv.errors)

    # ── 4. Full pipeline on real scraped data ──────────────────────────────────
    log.info("4. Full pipeline — real books data end-to-end:")

    soup = parser.make_soup(books_html.html)

    # Extract raw data using BS4
    titles = parser.get_all_text(soup, "h3 > a")
    prices = parser.get_all_text(soup, "p.price_color")
    availabilities = parser.get_all_text(soup, "p.availability")
    links = parser.get_all_attr(soup, "h3 > a", "href")

    # Build raw item dicts
    raw_books = []
    for i, (title, price, avail, link) in enumerate(
        zip(titles, prices, availabilities, links)
    ):
        raw_books.append({
            "title": title,
            "price_raw": price,
            "availability": avail,
            "url": f"https://books.toscrape.com/catalogue/{link.replace('../', '')}",
        })

    log.info("  Raw books extracted: {}", len(raw_books))

    # Stage 1 — Clean
    cleaned_books = cleaner.clean_items(raw_books)

    # Stage 2 — Transform
    book_transformer = DataTransformer(
        computed={
            "price": lambda item: DataCleaner.extract_number(
                item.get("price_raw", "") or ""
            ),
        },
        drop_fields=["price_raw"],
        add_metadata=True,
    )
    transformed_books = book_transformer.transform_items(cleaned_books)

    # Stage 3 — Validate
    book_validator = DataValidator(schema=BookSchema, strict=False)
    book_batch = book_validator.validate_batch(transformed_books)

    log.info("  Pipeline result: {}", book_batch)
    log.info("  First 3 valid books:")
    for book in book_batch.valid_items[:3]:
        log.info("  ✓ {} | £{} | {}",
                 book.get("title", "")[:35],
                 book.get("price"),
                 book.get("availability", "").strip())

    # ── 5. Quotes pipeline ────────────────────────────────────────────────────
    log.info("5. Full pipeline — quotes data:")

    tree = __import__("parser.lxml_parser", fromlist=["LxmlParser"]).LxmlParser()
    lxml_tree = tree.make_tree(quotes_html.html)

    quote_texts = tree.xpath_all_text(lxml_tree, "//span[@class='text']/text()")
    authors = tree.xpath_all_text(lxml_tree, "//small[@class='author']/text()")

    raw_quotes = [
        {
            "text": text,
            "author": author,
            "url": f"https://quotes.toscrape.com/page/1/#{i}",
        }
        for i, (text, author) in enumerate(zip(quote_texts, authors))
    ]

    cleaned_quotes = cleaner.clean_items(raw_quotes)
    quote_transformer = DataTransformer(add_metadata=True)
    transformed_quotes = quote_transformer.transform_items(cleaned_quotes)
    quote_validator = DataValidator(schema=QuoteSchema, strict=False)
    quote_batch = quote_validator.validate_batch(transformed_quotes)

    log.info("  Pipeline result: {}", quote_batch)
    log.info("  First 3 quotes:")
    for q in quote_batch.valid_items[:3]:
        log.info("  ✓ {} — {}",
                 q.get("text", "")[:50],
                 q.get("author"))

    log.info("=" * 60)
    log.success("Day 8 complete — full pipeline working end-to-end")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
