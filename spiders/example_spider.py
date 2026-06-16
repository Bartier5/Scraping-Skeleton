# ── spiders/example_spider.py ─────────────────────────────────────────────────
# Example spider — scrapes books.toscrape.com catalogue pages.
#
# This is the reference implementation showing how to wire all skeleton
# layers together in a real spider. Study this before writing your own.
#
# What this spider does:
#   1. Fetches one or more books.toscrape.com catalogue pages
#   2. Parses book titles, prices, ratings, availability
#   3. Runs data through full pipeline (clean → transform → validate)
#   4. Saves to configured storage backend
#   5. Returns run stats
#
# Run via CLI:
#   python main.py --spider example --mode single --url https://books.toscrape.com/catalogue/page-1.html
#   python main.py --spider example --mode batch --storage sqlite

import asyncio
from typing import Optional

from spiders.base_spider import BaseSpider
from pipeline.cleaner import DataCleaner
from pipeline.transformer import DataTransformer
from pipeline.validator import DataValidator, BookSchema
from utils.logger import log
from utils.url_utils import prepare_urls, build_paginated_urls


class ExampleSpider(BaseSpider):
    """
    Reference spider for books.toscrape.com.

    Demonstrates the complete data flow:
    Fetcher → Parser (BS4) → Cleaner → Transformer → Validator → Storage

    All pipeline components are initialized once in __init__ and reused
    across all pages — no re-initialization overhead per URL.
    """

    # Default URLs to scrape if none are provided
    DEFAULT_URLS = [
        "https://books.toscrape.com/catalogue/page-1.html",
    ]

    def __init__(self, **kwargs):
        super().__init__(name="ExampleSpider", **kwargs)

        # Initialize pipeline components once
        self._cleaner = DataCleaner()
        self._transformer = DataTransformer(
            computed={
                # Extract numeric price from "£51.77" → 51.77
                "price": lambda item: DataCleaner.extract_number(
                    item.get("price_raw", "") or ""
                ),
            },
            # drop price_raw after computing price
            # Note: drop_fields runs AFTER computed — by design
            add_metadata=True,
        )
        self._validator = DataValidator(schema=BookSchema, strict=False)

        log.debug("ExampleSpider: pipeline initialized")

    async def run(self, urls: list[str] = None, **kwargs) -> dict:
        """
        Scrapes books from the provided URLs.

        Args:
            urls: list of catalogue page URLs to scrape.
                  If None, scrapes DEFAULT_URLS.

        Returns:
            stats dict with counts of fetched, parsed, saved items
        """
        urls = prepare_urls(urls or self.DEFAULT_URLS)
        self.start_run(urls)

        async with self:   # ensures fetcher closes on exit
            for url in urls:
                await self._scrape_page(url)

        self.finish_run()
        return self.get_stats()

    async def _scrape_page(self, url: str) -> int:
        """
        Scrapes a single catalogue page — fetch → parse → pipeline → save.

        Args:
            url: the catalogue page URL

        Returns:
            number of items saved from this page
        """
        log.info("ExampleSpider: scraping {}", url)

        # ── Step 1: Fetch ─────────────────────────────────────────────────────
        result = await self.fetch(url)
        if result.failed:
            log.warning("ExampleSpider: fetch failed for {} — {}", url, result.error)
            return 0

        # ── Step 2: Parse ─────────────────────────────────────────────────────
        soup = self.parser.make_soup(result.html)

        titles      = self.parser.get_all_text(soup, "h3 > a")
        prices_raw  = self.parser.get_all_text(soup, "p.price_color")
        ratings     = self.parser.get_all_attr(soup, "p.star-rating", "class")
        avails      = self.parser.get_all_text(soup, "p.availability")
        links       = self.parser.get_all_attr(soup, "h3 > a", "href")

        if not titles:
            log.warning("ExampleSpider: no items found on {}", url)
            return 0

        # Build raw item dicts
        raw_items = []
        for title, price_raw, rating, avail, link in zip(
            titles, prices_raw, ratings, avails, links
        ):
            raw_items.append({
                "title":     title,
                "price_raw": price_raw,
                "rating":    " ".join(rating) if isinstance(rating, list) else rating,
                "availability": avail,
                "url": f"https://books.toscrape.com/catalogue/{link.replace('../', '')}",
            })

        log.debug("ExampleSpider: parsed {} raw items from {}", len(raw_items), url)
        self._stats["items_scraped"] += len(raw_items)

        # ── Step 3: Pipeline ──────────────────────────────────────────────────
        cleaned     = self._cleaner.clean_items(raw_items)
        transformed = self._transformer.transform_items(cleaned)
        batch       = self._validator.validate_batch(transformed)

        if batch.invalid_items:
            log.warning(
                "ExampleSpider: {} items failed validation on {}",
                len(batch.invalid_items), url
            )

        # ── Step 4: Save ──────────────────────────────────────────────────────
        saved = await self.save(batch.valid_items)
        log.info(
            "ExampleSpider: {} items saved from {}",
            saved, url
        )
        return saved

    @classmethod
    def build_page_urls(cls, total_pages: int, start_page: int = 1) -> list[str]:
        """
        Convenience method to generate multiple catalogue page URLs.

        Args:
            total_pages: how many pages to generate
            start_page:  starting page number

        Returns:
            list of catalogue page URLs

        Example:
            urls = ExampleSpider.build_page_urls(total_pages=5)
            # → ["https://books.toscrape.com/catalogue/page-1.html", ...]
        """
        return [
            f"https://books.toscrape.com/catalogue/page-{i}.html"
            for i in range(start_page, start_page + total_pages)
        ]
