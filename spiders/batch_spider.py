# ── spiders/batch_spider.py ───────────────────────────────────────────────────
# Batch spider — scrapes large URL lists with chunking, checkpointing,
# and progress tracking. The production-ready spider for client jobs.
#
# What makes this different from ExampleSpider?
#   ExampleSpider: sequential page-by-page, simple, good for <20 URLs
#   BatchSpider:   chunked concurrent, checkpointed, good for 50-1000+ URLs
#
# Features:
#   - Chunk-based processing via BatchFetcher
#   - Automatic checkpointing — resumable after interruption
#   - Delta scraping — skips URLs with unchanged content
#   - Per-result callback — process items as they arrive
#   - Progress reporting per chunk
#
# Run via CLI:
#   python main.py --spider batch --mode batch --concurrency 10 --storage sqlite

import asyncio
from typing import Optional, Callable

from spiders.base_spider import BaseSpider
from fetcher.batch_fetcher import BatchFetcher
from fetcher.base_fetcher import FetchResult
from storage.checkpoint_manager import CheckpointManager
from pipeline.cleaner import DataCleaner
from pipeline.transformer import DataTransformer
from pipeline.validator import DataValidator, BookSchema
from utils.logger import log
from utils.helpers import hash_content
from utils.url_utils import prepare_urls


class BatchSpider(BaseSpider):
    """
    Production batch spider with checkpointing and delta scraping.

    Designed for large recurring scrape jobs where:
    - You need to resume after interruption
    - You only want to re-process pages that actually changed
    - You need real-time progress updates per chunk
    - Memory efficiency matters (chunks, not all at once)
    """

    def __init__(
        self,
        checkpoint_db: str = "data/batch_checkpoints.db",
        chunk_size: int = None,
        delta_scraping: bool = True,    # skip unchanged pages
        **kwargs,
    ):
        """
        Args:
            checkpoint_db:   path to checkpoint SQLite database
            chunk_size:      URLs per batch chunk (defaults to concurrency * 2)
            delta_scraping:  if True, skip pages with unchanged content
            **kwargs:        passed to BaseSpider
        """
        super().__init__(name="BatchSpider", **kwargs)

        self._checkpoint_db = checkpoint_db
        self._chunk_size = chunk_size
        self._delta_scraping = delta_scraping
        self._checkpoint_manager: Optional[CheckpointManager] = None

        # Pipeline — same as ExampleSpider
        self._cleaner = DataCleaner()
        self._transformer = DataTransformer(
            computed={
                "price": lambda item: DataCleaner.extract_number(
                    item.get("price_raw", "") or ""
                ),
            },
            add_metadata=True,
        )
        self._validator = DataValidator(schema=BookSchema, strict=False)

        # Extended stats for batch jobs
        self._stats.update({
            "urls_skipped_checkpoint": 0,
            "urls_skipped_unchanged": 0,
            "chunks_processed": 0,
        })

        log.debug("BatchSpider: initialized (delta_scraping={})", delta_scraping)

    async def _get_checkpoint_manager(self) -> CheckpointManager:
        """Returns the CheckpointManager, initializing it if needed."""
        if self._checkpoint_manager is None:
            self._checkpoint_manager = CheckpointManager(
                db_path=self._checkpoint_db
            )
            await self._checkpoint_manager.init()
        return self._checkpoint_manager

    async def run(
        self,
        urls: list[str] = None,
        on_chunk_complete: Optional[Callable] = None,
        **kwargs,
    ) -> dict:
        """
        Scrapes a large list of URLs in chunks with checkpointing.

        Flow per chunk:
        1. Filter out already-checkpointed URLs (resumability)
        2. Fetch all URLs in chunk concurrently via BatchFetcher
        3. For each successful fetch:
           a. Check content hash — skip if unchanged (delta scraping)
           b. Parse → clean → transform → validate
           c. Save to storage
           d. Checkpoint the URL
        4. Report chunk progress
        5. Repeat for next chunk

        Args:
            urls:              list of URLs to scrape
            on_chunk_complete: optional callback after each chunk completes
                               signature: callback(chunk_num, results, stats)

        Returns:
            stats dict
        """
        if not urls:
            log.warning("BatchSpider: no URLs provided")
            return self.get_stats()

        urls = prepare_urls(urls)
        self.start_run(urls)

        checkpoint = await self._get_checkpoint_manager()

        # Filter to only pending URLs — skip already done
        pending_urls = await checkpoint.get_pending(urls)
        skipped_checkpoint = len(urls) - len(pending_urls)
        self._stats["urls_skipped_checkpoint"] = skipped_checkpoint

        if skipped_checkpoint:
            log.info(
                "BatchSpider: {} URLs already checkpointed — skipping",
                skipped_checkpoint
            )

        if not pending_urls:
            log.info("BatchSpider: all URLs already processed")
            self.finish_run()
            return self.get_stats()

        # Use BatchFetcher for chunk-based concurrent fetching
        chunk_size = self._chunk_size or (self.concurrency * 2)

        batch_fetcher = BatchFetcher(
            concurrency=self.concurrency,
            chunk_size=chunk_size,
        )

        chunk_num = 0

        async def on_result(fetch_result: FetchResult) -> None:
            """
            Callback fired by BatchFetcher after each successful fetch.
            Processes result immediately — no waiting for whole chunk.
            """
            await self._process_result(fetch_result, checkpoint)

        try:
            async with batch_fetcher:
                results = await batch_fetcher.fetch_batch(
                    pending_urls,
                    on_result=on_result,
                    prepare=False,   # already prepared above
                )

            # Count chunks processed
            self._stats["chunks_processed"] = (
                len(pending_urls) + chunk_size - 1
            ) // chunk_size

            if on_chunk_complete:
                on_chunk_complete(chunk_num, results, self.get_stats())

        except Exception as e:
            log.error("BatchSpider: fatal error during batch — {}", str(e))
            self._stats["errors"].append({"error": str(e)})

        self.finish_run()
        return self.get_stats()

    async def _process_result(
        self,
        result: FetchResult,
        checkpoint: CheckpointManager,
    ) -> None:
        """
        Processes a single fetch result through the full pipeline.
        Called by the on_result callback after each successful fetch.

        Args:
            result:     the FetchResult from the fetcher
            checkpoint: the CheckpointManager for recording progress
        """
        if result.failed:
            log.warning("BatchSpider: skipping failed fetch — {}", result.url)
            await checkpoint.mark_failed(result.url, reason=result.error or "")
            return

        # ── Delta scraping: skip unchanged pages ──────────────────────────────
        if self._delta_scraping and result.html:
            content_hash = hash_content(result.html)
            changed = await checkpoint.has_changed(result.url, content_hash)
            if not changed:
                self._stats["urls_skipped_unchanged"] += 1
                log.debug("BatchSpider: content unchanged — skipping {}", result.url)
                return
        else:
            content_hash = hash_content(result.html) if result.html else ""

        # ── Parse ─────────────────────────────────────────────────────────────
        soup = self.parser.make_soup(result.html)

        titles     = self.parser.get_all_text(soup, "h3 > a")
        prices_raw = self.parser.get_all_text(soup, "p.price_color")
        ratings    = self.parser.get_all_attr(soup, "p.star-rating", "class")
        avails     = self.parser.get_all_text(soup, "p.availability")
        links      = self.parser.get_all_attr(soup, "h3 > a", "href")

        if not titles:
            log.debug("BatchSpider: no items found on {}", result.url)
            await checkpoint.mark_done(result.url, content_hash=content_hash)
            return

        raw_items = []
        for title, price_raw, rating, avail, link in zip(
            titles, prices_raw, ratings, avails, links
        ):
            raw_items.append({
                "title":        title,
                "price_raw":    price_raw,
                "rating":       " ".join(rating) if isinstance(rating, list) else rating,
                "availability": avail,
                "url": f"https://books.toscrape.com/catalogue/{link.replace('../', '')}",
            })

        self._stats["items_scraped"] += len(raw_items)

        # ── Pipeline ──────────────────────────────────────────────────────────
        cleaned     = self._cleaner.clean_items(raw_items)
        transformed = self._transformer.transform_items(cleaned)
        batch       = self._validator.validate_batch(transformed)

        # ── Save ──────────────────────────────────────────────────────────────
        if batch.valid_items:
            save_result = await self.storage.save(batch.valid_items)
            self._stats["items_saved"] += save_result.rows_saved

        # ── Checkpoint ────────────────────────────────────────────────────────
        await checkpoint.mark_done(result.url, content_hash=content_hash)
        log.debug(
            "BatchSpider: {} items from {} → checkpointed",
            len(batch.valid_items), result.url
        )

    async def get_checkpoint_stats(self) -> dict:
        """Returns checkpoint progress stats for this batch job."""
        checkpoint = await self._get_checkpoint_manager()
        return await checkpoint.get_stats()

    async def reset_checkpoints(self) -> bool:
        """Clears all checkpoints — forces full re-scrape on next run."""
        checkpoint = await self._get_checkpoint_manager()
        return await checkpoint.reset()
