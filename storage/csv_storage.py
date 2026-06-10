# ── storage/csv_storage.py ────────────────────────────────────────────────────
# CSV storage backend — saves scraped data to flat CSV files.
#
# When to use CSV storage:
#   - Quick one-off scrape jobs where no database is needed
#   - Delivering data directly to clients who work in Excel
#   - Lightweight jobs with under ~100k rows
#   - When simplicity matters more than query capability
#
# Inherits from BaseStorage — implements all five required methods.

import csv
import os
import pandas as pd
from typing import Any, Optional
from pathlib import Path

from storage.base_storage import BaseStorage, SaveResult
from utils.logger import log
from utils.helpers import ensure_dir, get_output_path


class CsvStorage(BaseStorage):
    """
    Flat-file CSV storage backend.

    Appends new records to a CSV file on each save() call.
    The file is created on first save if it doesn't exist.
    Headers are written automatically from the first item's keys.

    Supports:
    - Append mode (default) — adds rows to existing file
    - Overwrite mode — replaces file on each save
    - Deduplication via exists() check before saving
    """

    def __init__(
        self,
        filepath: str = "data/output.csv",
        mode: str = "append",           # "append" or "overwrite"
        encoding: str = "utf-8-sig",    # utf-8-sig adds BOM for Excel compatibility
        config: dict = None,
    ):
        """
        Args:
            filepath: path to the CSV file
            mode:     "append" adds to existing file
                      "overwrite" replaces file on each save
            encoding: file encoding — utf-8-sig recommended for Excel
        """
        super().__init__(config)
        self.filepath = filepath
        self.mode = mode
        self.encoding = encoding

        # Ensure parent directory exists
        ensure_dir(str(Path(filepath).parent))
        log.debug("CsvStorage initialized (filepath={}, mode={})", filepath, mode)

    async def save(self, data: list[dict], **kwargs) -> SaveResult:
        """
        Saves a list of dicts to the CSV file.

        On first write: creates file and writes headers + rows.
        On subsequent writes (append mode): appends rows without repeating headers.

        Args:
            data:     list of dicts to save
            **kwargs: optional overrides:
                      - fieldnames (list): column order override

        Returns:
            SaveResult with rows_saved count
        """
        if not data:
            return SaveResult(success=True, rows_saved=0, backend="csv")

        try:
            # Determine field names from first item or kwargs override
            fieldnames = kwargs.get("fieldnames", list(data[0].keys()))

            # Check if file exists and has content to decide on header writing
            file_exists = os.path.isfile(self.filepath) and os.path.getsize(self.filepath) > 0

            # Determine write mode
            # "a" = append to existing file
            # "w" = overwrite file (used in overwrite mode OR first write)
            write_mode = "a" if (self.mode == "append" and file_exists) else "w"

            with open(self.filepath, write_mode, newline="", encoding=self.encoding) as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=fieldnames,
                    extrasaction="ignore",   # ignore dict keys not in fieldnames
                )

                # Write headers only on first write or overwrite mode
                if write_mode == "w":
                    writer.writeheader()

                writer.writerows(data)

            log.info("CsvStorage: saved {} rows to {}", len(data), self.filepath)
            return SaveResult(
                success=True,
                rows_saved=len(data),
                backend="csv",
                metadata={"filepath": self.filepath},
            )

        except Exception as e:
            return self.make_error_result(e, backend="csv")

    async def load(self, limit: int = None, **kwargs) -> list[dict]:
        """
        Loads records from the CSV file as a list of dicts.

        Args:
            limit: max number of rows to return (None = all)

        Returns:
            list of dicts, one per CSV row
        """
        if not os.path.isfile(self.filepath):
            log.info("CsvStorage: file not found — {}", self.filepath)
            return []

        try:
            rows = []
            with open(self.filepath, "r", encoding=self.encoding) as f:
                reader = csv.DictReader(f)
                for i, row in enumerate(reader):
                    if limit and i >= limit:
                        break
                    rows.append(dict(row))

            log.debug("CsvStorage: loaded {} rows from {}", len(rows), self.filepath)
            return rows

        except Exception as e:
            log.error("CsvStorage.load failed: {}", str(e))
            return []

    async def exists(self, key: str, value: Any) -> bool:
        """
        Checks if any row has the given key=value.
        Loads the entire file to check — for large files use SQLite instead.

        Args:
            key:   column name to check
            value: value to look for

        Returns:
            True if any row matches
        """
        rows = await self.load()
        return any(str(row.get(key, "")) == str(value) for row in rows)

    async def clear(self) -> bool:
        """Deletes the CSV file entirely."""
        try:
            if os.path.isfile(self.filepath):
                os.remove(self.filepath)
                log.debug("CsvStorage: deleted {}", self.filepath)
            return True
        except Exception as e:
            log.error("CsvStorage.clear failed: {}", str(e))
            return False

    async def count(self) -> int:
        """Returns the number of data rows in the CSV (excludes header)."""
        if not os.path.isfile(self.filepath):
            return 0
        try:
            with open(self.filepath, "r", encoding=self.encoding) as f:
                # subtract 1 for header row
                return max(0, sum(1 for _ in f) - 1)
        except Exception as e:
            log.error("CsvStorage.count failed: {}", str(e))
            return 0

    def to_dataframe(self) -> pd.DataFrame:
        """
        Loads the CSV file directly into a pandas DataFrame.
        Convenience method for passing data to the pandas layer.
        """
        if not os.path.isfile(self.filepath):
            return pd.DataFrame()
        return pd.read_csv(self.filepath, encoding=self.encoding)
