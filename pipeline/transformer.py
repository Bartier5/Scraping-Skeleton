# ── pipeline/transformer.py ───────────────────────────────────────────────────
# Data transformer — the second stage of the pipeline.
#
# What does the transformer do?
#   Takes cleaned dicts from the cleaner and applies business logic:
#   - Rename fields to match your storage schema
#   - Remove fields you don't need
#   - Add computed fields (e.g. scraped_at timestamp)
#   - Type-cast values (string "9.99" → float 9.99)
#   - Normalize categories, statuses, and other enumerable values
#
# Pipeline position:
#   Parser → Cleaner → [Transformer] → Validator → Storage
#
# Rule: the transformer changes the SHAPE of the data.
#   The cleaner normalized values. The transformer restructures the dict.
#   After the transformer, the dict should match your storage schema exactly.

from datetime import datetime, timezone
from typing import Any, Callable, Optional
from utils.logger import log
from utils.helpers import timestamp, slugify


class DataTransformer:
    """
    Transforms cleaned scraped data into storage-ready records.

    Can be configured with:
    - field_map:     rename fields {"old_name": "new_name"}
    - keep_fields:   whitelist — only these fields survive
    - drop_fields:   blacklist — these fields are removed
    - type_casts:    cast field values to specific types
    - computed:      add new fields derived from existing ones
    - normalizers:   custom normalization functions per field

    Example:
        transformer = DataTransformer(
            field_map={"title": "name", "price_color": "price"},
            keep_fields=["name", "price", "url"],
            type_casts={"price": float},
        )
        result = transformer.transform_item(cleaned_item)
    """

    def __init__(
        self,
        field_map: dict[str, str] = None,
        keep_fields: list[str] = None,
        drop_fields: list[str] = None,
        type_casts: dict[str, type] = None,
        computed: dict[str, Callable] = None,
        add_metadata: bool = True,
    ):
        """
        Args:
            field_map:    maps old field names to new ones
                          e.g. {"price_color": "price", "title": "name"}
            keep_fields:  if provided, only these fields appear in output
                          applied AFTER field_map, so use new names
            drop_fields:  fields to remove from output
                          applied AFTER field_map, so use new names
            type_casts:   cast field values to a Python type
                          e.g. {"price": float, "stock_count": int}
            computed:     add new fields using a function that receives the item
                          e.g. {"slug": lambda item: slugify(item["name"])}
            add_metadata: if True, adds scraped_at and source metadata fields
        """
        self.field_map = field_map or {}
        self.keep_fields = set(keep_fields) if keep_fields else None
        self.drop_fields = set(drop_fields) if drop_fields else set()
        self.type_casts = type_casts or {}
        self.computed = computed or {}
        self.add_metadata = add_metadata

        log.debug("DataTransformer initialized")

    def transform_item(self, item: dict) -> dict:
        """
        Transforms a single cleaned dict through the full transformation pipeline.

        Steps applied in order:
        1. Rename fields using field_map
        2. Remove drop_fields
        3. Filter to keep_fields only (if specified)
        4. Apply type_casts
        5. Add computed fields
        6. Add metadata (scraped_at, etc.)

        Args:
            item: cleaned dict from DataCleaner

        Returns:
            transformed dict ready for validation and storage
        """
        if not item:
            return {}

        result = dict(item)   # work on a copy — never mutate the input

        # Step 1 — rename fields
        if self.field_map:
            result = self._apply_field_map(result)

        # Step 2 — remove dropped fields
        if self.drop_fields:
            result = {k: v for k, v in result.items() if k not in self.drop_fields}

        # Step 3 — filter to keep_fields whitelist
        if self.keep_fields:
            result = {k: v for k, v in result.items() if k in self.keep_fields}

        # Step 4 — apply type casts
        if self.type_casts:
            result = self._apply_type_casts(result)

        # Step 5 — add computed fields
        if self.computed:
            result = self._apply_computed(result)

        # Step 6 — add scrape metadata
        if self.add_metadata:
            result = self._add_metadata(result)

        return result

    def transform_items(self, items: list[dict]) -> list[dict]:
        """
        Transforms a list of cleaned dicts.
        Skips None/empty items. Logs count.

        Args:
            items: list of cleaned dicts

        Returns:
            list of transformed dicts
        """
        if not items:
            return []

        transformed = [self.transform_item(item) for item in items if item]
        log.debug("DataTransformer: transformed {} items", len(transformed))
        return transformed

    def _apply_field_map(self, item: dict) -> dict:
        """
        Renames fields according to field_map.
        Fields not in field_map are kept with their original names.

        Example:
            field_map = {"price_color": "price"}
            item = {"title": "Book", "price_color": "$9.99", "rating": 3}
            result = {"title": "Book", "price": "$9.99", "rating": 3}
        """
        result = {}
        for key, value in item.items():
            # Use mapped name if available, otherwise keep original
            new_key = self.field_map.get(key, key)
            result[new_key] = value
        return result

    def _apply_type_casts(self, item: dict) -> dict:
        """
        Casts field values to specified Python types.
        If a cast fails, the original value is kept and a warning is logged.

        Example:
            type_casts = {"price": float, "page_count": int}
            item = {"price": "9.99", "page_count": "312"}
            result = {"price": 9.99, "page_count": 312}
        """
        result = dict(item)
        for field, target_type in self.type_casts.items():
            if field not in result:
                continue

            value = result[field]
            if value == "" or value is None:
                continue   # skip empty values — don't cast None to 0

            try:
                if target_type == float:
                    # Extract numeric portion first — handles "$9.99" → 9.99
                    numeric = re.sub(r"[^\d.]", "", str(value))
                    result[field] = float(numeric) if numeric else value
                elif target_type == int:
                    numeric = re.sub(r"[^\d]", "", str(value))
                    result[field] = int(numeric) if numeric else value
                elif target_type == bool:
                    result[field] = str(value).lower() in ("true", "1", "yes", "in stock")
                else:
                    result[field] = target_type(value)
            except (ValueError, TypeError) as e:
                log.warning(
                    "DataTransformer: failed to cast '{}' to {} for field '{}': {}",
                    value, target_type.__name__, field, str(e)
                )

        return result

    def _apply_computed(self, item: dict) -> dict:
        """
        Adds new fields derived from existing ones using callable functions.
        If a computed function raises, the field is set to None and logged.

        Example:
            computed = {
                "slug": lambda item: slugify(item.get("name", "")),
                "price_gbp": lambda item: round(item.get("price", 0) * 0.79, 2),
            }
        """
        result = dict(item)
        for field, fn in self.computed.items():
            try:
                result[field] = fn(result)
            except Exception as e:
                log.warning(
                    "DataTransformer: computed field '{}' failed: {}", field, str(e)
                )
                result[field] = None
        return result

    def _add_metadata(self, item: dict) -> dict:
        """
        Adds standard scrape metadata fields to every record.
        These are useful for tracking when data was collected.

        Fields added:
            scraped_at: ISO 8601 timestamp of when this record was processed
        """
        result = dict(item)
        # Only add if not already present — don't overwrite existing timestamps
        if "scraped_at" not in result:
            result["scraped_at"] = datetime.now(timezone.utc).isoformat()
        return result


# ── Regex import needed by _apply_type_casts ─────────────────────────────────
import re
