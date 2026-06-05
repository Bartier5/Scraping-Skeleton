# ── storage/base_storage.py ───────────────────────────────────────────────────
# Abstract base class for all storage backends in the scraper skeleton.
#
# What does storage do?
#   Takes structured data from the pipeline and saves it somewhere permanent.
#   Input:  list of dicts   (e.g. [{"title": "Book", "price": "$9.99"}, ...])
#   Output: saved to CSV, SQLite, PostgreSQL, or any other backend
#
# The spider always calls storage.save(data) — it never knows or cares
# whether that data ends up in a CSV file or a PostgreSQL database.
#
# Storage backends that will inherit from this (Days 10 & 11):
#   - CsvStorage       (flat file — quick, no setup needed)
#   - SqliteStorage    (local DB — good for medium projects, checkpointing)
#   - PostgresStorage  (production DB — for client retainer work)

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Any
from utils.logger import log


# ── SaveResult ────────────────────────────────────────────────────────────────

@dataclass
class SaveResult:
    """
    Standardized result returned after every save operation.

    Fields:
        success:       True if data was saved without error
        rows_saved:    how many records were written
        rows_skipped:  how many records were skipped (e.g. duplicates)
        backend:       which storage backend handled this save
        error:         error message if save failed, None if successful
        metadata:      any extra backend-specific info
    """
    success: bool = False
    rows_saved: int = 0
    rows_skipped: int = 0
    backend: str = ""                           # e.g. "csv", "sqlite", "postgres"
    error: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    def __str__(self) -> str:
        status = "OK" if self.success else "FAILED"
        return (f"SaveResult[{status}] backend={self.backend} "
                f"saved={self.rows_saved} skipped={self.rows_skipped}")


# ── BaseStorage ───────────────────────────────────────────────────────────────

class BaseStorage(ABC):
    """
    Abstract base class all storage backends must inherit from.

    Every storage backend must be able to:
    - save()     → write new records
    - load()     → read records back
    - exists()   → check if a record already exists (for deduplication)
    - clear()    → wipe all stored data
    - count()    → return total record count
    """

    def __init__(self, config: dict = None):
        """
        Args:
            config: optional overrides
                    e.g. {"filepath": "data/output.csv", "table": "products"}
        """
        self.config = config or {}
        log.debug("{} initialized", self.__class__.__name__)

    @abstractmethod
    async def save(self, data: list[dict], **kwargs) -> SaveResult:
        """
        Save a list of records to the storage backend.

        Args:
            data:     list of dicts — each dict is one scraped record
            **kwargs: optional backend-specific overrides (table name, mode...)

        Returns:
            SaveResult with rows_saved, rows_skipped, and success status
        """
        ...

    @abstractmethod
    async def load(self, limit: int = None, **kwargs) -> list[dict]:
        """
        Load records from the storage backend.

        Args:
            limit:    max number of records to return (None = all)
            **kwargs: optional filters (e.g. where conditions for SQL backends)

        Returns:
            list of dicts, one per stored record
        """
        ...

    @abstractmethod
    async def exists(self, key: str, value: Any) -> bool:
        """
        Check if a record with the given key-value pair already exists.
        Used for deduplication — avoids saving the same record twice.

        Example:
            already_stored = await storage.exists("url", "https://example.com/page-1")
            if not already_stored:
                await storage.save([item])

        Args:
            key:   field name to check (e.g. "url", "product_id")
            value: value to look for

        Returns:
            True if a matching record exists, False otherwise
        """
        ...

    @abstractmethod
    async def clear(self) -> bool:
        """
        Delete all stored records.
        Used between scrape jobs or during testing.

        Returns:
            True if successful, False if an error occurred
        """
        ...

    @abstractmethod
    async def count(self) -> int:
        """
        Return the total number of records currently stored.

        Returns:
            integer record count
        """
        ...

    def make_error_result(self, error: Exception, backend: str = "") -> SaveResult:
        """
        Builds a failed SaveResult from an exception.
        Shared helper so all backends handle errors consistently.
        """
        log.error("{} save failed: {}", self.__class__.__name__, str(error))
        return SaveResult(
            success=False,
            error=str(error),
            backend=backend or self.__class__.__name__,
        )

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(config={self.config})"
