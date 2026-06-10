# ── storage/checkpoint_manager.py ────────────────────────────────────────────
# Standalone checkpoint manager for resumable scraping.
#
# What is checkpointing?
#   When a large scrape job is interrupted (crash, network failure, timeout),
#   checkpointing lets you resume from where you left off instead of
#   restarting from scratch. Every successfully processed URL is recorded.
#   On the next run, already-processed URLs are skipped automatically.
#
# This is a standalone manager separate from SqliteStorage.
# Use it when you want checkpointing without full SQLite storage,
# or when you need to checkpoint across multiple storage backends.
#
# Also handles content hashing for delta scraping:
#   Store the MD5 hash of page content on first scrape.
#   On next run, compare new hash to stored hash.
#   If hashes differ → content changed → re-process.
#   If hashes match → content unchanged → skip.

import aiosqlite
import json
from datetime import datetime, timezone
from typing import Optional
from pathlib import Path

from utils.logger import log
from utils.helpers import ensure_dir, hash_url, hash_content


class CheckpointManager:
    """
    Manages scrape progress using a SQLite-backed checkpoint store.

    Usage in a spider:
        manager = CheckpointManager(db_path="data/checkpoints.db")
        await manager.init()

        for url in urls:
            if await manager.is_done(url):
                continue   # already scraped
            result = await fetcher.async_fetch(url)
            # ... parse and save result ...
            await manager.mark_done(url, content_hash=hash_content(result.html))

        stats = await manager.get_stats()
        log.info("Scraped {}/{} URLs", stats["done"], stats["total_seen"])
    """

    def __init__(self, db_path: str = "data/checkpoints.db"):
        """
        Args:
            db_path: path to the SQLite file used for checkpoint storage.
                     Separate from the main data database for clean separation.
        """
        self.db_path = db_path
        ensure_dir(str(Path(db_path).parent))
        log.debug("CheckpointManager initialized (db={})", db_path)

    async def init(self) -> None:
        """
        Creates the checkpoints table if it doesn't exist.
        Call this once before using the manager in a scrape run.

        Table schema:
            url_hash:     MD5 of the URL — primary key (faster than storing full URL)
            url:          the full URL for reference
            content_hash: MD5 of page content — for delta scraping
            status:       "done", "failed", "skipped"
            scraped_at:   when this checkpoint was created
            metadata:     JSON blob for any extra info
        """
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS checkpoints (
                    url_hash     TEXT PRIMARY KEY,
                    url          TEXT NOT NULL,
                    content_hash TEXT DEFAULT '',
                    status       TEXT DEFAULT 'done',
                    scraped_at   TEXT DEFAULT (datetime('now')),
                    metadata     TEXT DEFAULT '{}'
                )
            """)
            # Index on status for fast filtering by done/failed/skipped
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_checkpoints_status
                ON checkpoints (status)
            """)
            await conn.commit()
        log.debug("CheckpointManager: checkpoint table ready")

    async def mark_done(
        self,
        url: str,
        content_hash: str = "",
        metadata: dict = None,
    ) -> None:
        """
        Records a URL as successfully scraped.

        Args:
            url:          the URL that was scraped
            content_hash: MD5 hash of the page content (for delta scraping)
                          use hash_content(result.html) from utils.helpers
            metadata:     any extra info to store (e.g. item count, duration)
        """
        url_hash = hash_url(url)   # store hash instead of full URL as primary key
        meta_json = json.dumps(metadata or {})
        scraped_at = datetime.now(timezone.utc).isoformat()

        try:
            async with aiosqlite.connect(self.db_path) as conn:
                # INSERT OR REPLACE — updates if URL was previously checkpointed
                await conn.execute("""
                    INSERT OR REPLACE INTO checkpoints
                    (url_hash, url, content_hash, status, scraped_at, metadata)
                    VALUES (?, ?, ?, 'done', ?, ?)
                """, (url_hash, url, content_hash, scraped_at, meta_json))
                await conn.commit()
        except Exception as e:
            log.error("CheckpointManager.mark_done failed for {}: {}", url, str(e))

    async def mark_failed(self, url: str, reason: str = "") -> None:
        """
        Records a URL as failed — it was attempted but didn't succeed.
        Failed URLs can be retried on the next run.

        Args:
            url:    the URL that failed
            reason: error message or description of why it failed
        """
        url_hash = hash_url(url)
        meta_json = json.dumps({"reason": reason})
        scraped_at = datetime.now(timezone.utc).isoformat()

        try:
            async with aiosqlite.connect(self.db_path) as conn:
                await conn.execute("""
                    INSERT OR REPLACE INTO checkpoints
                    (url_hash, url, content_hash, status, scraped_at, metadata)
                    VALUES (?, ?, '', 'failed', ?, ?)
                """, (url_hash, url, scraped_at, meta_json))
                await conn.commit()
        except Exception as e:
            log.error("CheckpointManager.mark_failed failed: {}", str(e))

    async def is_done(self, url: str) -> bool:
        """
        Returns True if the URL has been successfully checkpointed.
        Failed URLs return False so they can be retried.

        Args:
            url: the URL to check

        Returns:
            True if successfully scraped, False if not yet done or failed
        """
        url_hash = hash_url(url)
        try:
            async with aiosqlite.connect(self.db_path) as conn:
                async with conn.execute(
                    "SELECT 1 FROM checkpoints WHERE url_hash = ? AND status = 'done' LIMIT 1",
                    (url_hash,)
                ) as cursor:
                    return await cursor.fetchone() is not None
        except Exception:
            return False

    async def has_changed(self, url: str, new_content_hash: str) -> bool:
        """
        Compares new content hash with stored hash to detect page changes.
        This is the delta scraping check — only reprocess if content changed.

        Args:
            url:              the URL to check
            new_content_hash: MD5 of the freshly fetched page content
                              use hash_content(result.html) from utils.helpers

        Returns:
            True if content changed (or URL not seen before)
            False if content is identical to last scrape
        """
        url_hash = hash_url(url)
        try:
            async with aiosqlite.connect(self.db_path) as conn:
                async with conn.execute(
                    "SELECT content_hash FROM checkpoints WHERE url_hash = ? LIMIT 1",
                    (url_hash,)
                ) as cursor:
                    row = await cursor.fetchone()
                    if row is None:
                        return True   # never seen before → treat as changed
                    stored_hash = row[0]
                    changed = stored_hash != new_content_hash
                    if changed:
                        log.debug("CheckpointManager: content changed for {}", url)
                    return changed
        except Exception:
            return True   # on error, assume changed to be safe

    async def get_pending(self, all_urls: list[str]) -> list[str]:
        """
        Filters a URL list to only those not yet done.
        Efficient batch check — one query instead of N individual is_done() calls.

        Args:
            all_urls: full list of URLs to scrape

        Returns:
            list of URLs that still need to be scraped
        """
        if not all_urls:
            return []

        # Hash all URLs for batch lookup
        url_hash_map = {hash_url(url): url for url in all_urls}
        done_hashes = set()

        try:
            async with aiosqlite.connect(self.db_path) as conn:
                # Get all done checkpoints in one query
                async with conn.execute(
                    "SELECT url_hash FROM checkpoints WHERE status = 'done'"
                ) as cursor:
                    rows = await cursor.fetchall()
                    done_hashes = {row[0] for row in rows}

        except Exception as e:
            log.error("CheckpointManager.get_pending failed: {}", str(e))
            return all_urls   # on error return all URLs to be safe

        pending = [
            url for url_hash, url in url_hash_map.items()
            if url_hash not in done_hashes
        ]

        skipped = len(all_urls) - len(pending)
        if skipped > 0:
            log.info(
                "CheckpointManager: {} already done, {} pending",
                skipped, len(pending)
            )

        return pending

    async def get_stats(self) -> dict:
        """
        Returns summary statistics about the checkpoint database.

        Returns:
            dict with total_seen, done, failed, skipped counts
        """
        try:
            async with aiosqlite.connect(self.db_path) as conn:
                async with conn.execute("""
                    SELECT status, COUNT(*) as count
                    FROM checkpoints
                    GROUP BY status
                """) as cursor:
                    rows = await cursor.fetchall()
                    counts = {row[0]: row[1] for row in rows}

            return {
                "total_seen": sum(counts.values()),
                "done":       counts.get("done", 0),
                "failed":     counts.get("failed", 0),
                "skipped":    counts.get("skipped", 0),
            }
        except Exception:
            return {"total_seen": 0, "done": 0, "failed": 0, "skipped": 0}

    async def reset(self) -> bool:
        """
        Clears all checkpoints — use when starting a completely fresh run.
        Does not delete the database file, just clears the table.
        """
        try:
            async with aiosqlite.connect(self.db_path) as conn:
                await conn.execute("DELETE FROM checkpoints")
                await conn.commit()
            log.info("CheckpointManager: all checkpoints cleared")
            return True
        except Exception as e:
            log.error("CheckpointManager.reset failed: {}", str(e))
            return False
