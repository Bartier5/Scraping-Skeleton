# ── spiders/base_spider.py ────────────────────────────────────────────────────
# Abstract base class for all spiders in the scraper skeleton.
#
# What is a spider?
#   A spider is the top-level coordinator — it wires all the layers together:
#   fetcher → parser → pipeline → storage. It's the only file you write
#   per job. Everything else in the skeleton stays untouched.
#
# This base class provides:
#   - Standard __init__ that accepts all layer components
#   - Abstract run() method every spider must implement
#   - Shared utilities: stats tracking, anti-bot injection, logging
#   - Context manager support for clean resource management

import asyncio
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional

from fetcher.base_fetcher import BaseFetcher, FetchResult
from parser.base_parser import BaseParser
from storage.base_storage import BaseStorage
from utils.logger import log
from config.config import Config


class BaseSpider(ABC):
    """
    Abstract base class all spiders must inherit from.

    Provides the wiring between all skeleton layers and enforces
    a consistent interface. Concrete spiders implement run() only.

    Usage:
        class MySpider(BaseSpider):
            async def run(self, urls: list[str]) -> dict:
                for url in urls:
                    result = await self.fetch(url)
                    if result.success:
                        items = self.parse(result.html, url)
                        await self.save(items)
                return self.get_stats()
    """

    def __init__(
        self,
        storage: BaseStorage = None,
        fetcher: BaseFetcher = None,
        parser: BaseParser = None,
        concurrency: int = None,
        name: str = None,
    ):
        """
        Args:
            storage:     storage backend — if None, uses SqliteStorage
            fetcher:     fetcher to use — if None, uses AsyncFetcher
            parser:      parser to use — if None, uses BS4Parser
            concurrency: max concurrent requests
            name:        spider name for logging (defaults to class name)
        """
        self.name = name or self.__class__.__name__
        self.concurrency = concurrency or Config.CONCURRENCY

        # Lazy-load defaults so spiders don't need to import everything
        self._storage = storage
        self._fetcher = fetcher
        self._parser = parser

        # Stats tracking — updated during run()
        self._stats = {
            "spider": self.name,
            "started_at": None,
            "finished_at": None,
            "urls_total": 0,
            "urls_fetched": 0,
            "urls_failed": 0,
            "items_scraped": 0,
            "items_saved": 0,
            "errors": [],
        }

        log.debug("Spider '{}' initialized", self.name)

    @property
    def storage(self) -> BaseStorage:
        """Returns storage backend, creating default if not set."""
        if self._storage is None:
            from storage.sqlite_storage import SqliteStorage
            self._storage = SqliteStorage(
                db_path=f"data/{self.name.lower()}.db"
            )
        return self._storage

    @property
    def fetcher(self) -> BaseFetcher:
        """Returns fetcher, creating default AsyncFetcher if not set."""
        if self._fetcher is None:
            from fetcher.async_fetcher import AsyncFetcher
            self._fetcher = AsyncFetcher(concurrency=self.concurrency)
        return self._fetcher

    @property
    def parser(self) -> BaseParser:
        """Returns parser, creating default BS4Parser if not set."""
        if self._parser is None:
            from parser.bs4_parser import BS4Parser
            self._parser = BS4Parser()
        return self._parser

    @abstractmethod
    async def run(self, urls: list[str] = None, **kwargs) -> dict:
        """
        Main spider method — must be implemented by every spider.

        Args:
            urls:     list of URLs to scrape
            **kwargs: any spider-specific options

        Returns:
            stats dict from get_stats()
        """
        ...

    async def fetch(self, url: str, **kwargs) -> FetchResult:
        """
        Fetches a single URL using the configured fetcher.
        Updates stats automatically.

        Args:
            url:      the URL to fetch
            **kwargs: passed to fetcher.async_fetch()

        Returns:
            FetchResult
        """
        result = await self.fetcher.async_fetch(url, **kwargs)
        self._stats["urls_fetched"] += 1
        if result.failed:
            self._stats["urls_failed"] += 1
            self._stats["errors"].append({
                "url": url,
                "error": result.error,
            })
        return result

    async def fetch_many(self, urls: list[str], **kwargs) -> list[FetchResult]:
        """
        Fetches multiple URLs concurrently using the configured fetcher.
        Updates stats automatically.

        Args:
            urls:     list of URLs to fetch
            **kwargs: passed to fetcher.fetch_many()

        Returns:
            list of FetchResult
        """
        results = await self.fetcher.fetch_many(urls, **kwargs)
        for result in results:
            self._stats["urls_fetched"] += 1
            if result.failed:
                self._stats["urls_failed"] += 1
                self._stats["errors"].append({
                    "url": result.url,
                    "error": result.error,
                })
        return results

    def parse(self, html: str, url: str = "") -> list[dict]:
        """
        Parses HTML using the configured parser.
        Returns the extracted data as a list of dicts.

        Args:
            html: raw HTML from the fetcher
            url:  source URL for traceability

        Returns:
            list of extracted item dicts
        """
        result = self.parser.parse(html, url)
        self._stats["items_scraped"] += result.item_count
        return result.data

    async def save(self, items: list[dict]) -> int:
        """
        Saves items to the configured storage backend.
        Updates stats automatically.

        Args:
            items: list of dicts to save

        Returns:
            number of rows saved
        """
        if not items:
            return 0

        result = await self.storage.save(items)
        self._stats["items_saved"] += result.rows_saved
        return result.rows_saved

    def start_run(self, urls: list[str] = None) -> None:
        """Records run start time and URL count in stats."""
        self._stats["started_at"] = datetime.now(timezone.utc).isoformat()
        self._stats["urls_total"] = len(urls) if urls else 0
        log.info("Spider '{}' starting — {} URLs", self.name, self._stats["urls_total"])

    def finish_run(self) -> None:
        """Records run finish time and logs final stats."""
        self._stats["finished_at"] = datetime.now(timezone.utc).isoformat()
        log.info(
            "Spider '{}' finished — fetched={} failed={} items={} saved={}",
            self.name,
            self._stats["urls_fetched"],
            self._stats["urls_failed"],
            self._stats["items_scraped"],
            self._stats["items_saved"],
        )

    def get_stats(self) -> dict:
        """Returns the current stats dict."""
        return dict(self._stats)

    async def close(self) -> None:
        """Closes fetcher session. Called automatically by context manager."""
        if self._fetcher:
            if hasattr(self._fetcher, "close"):
                try:
                    await self._fetcher.close()
                except Exception:
                    pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
        return False

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(concurrency={self.concurrency})"
