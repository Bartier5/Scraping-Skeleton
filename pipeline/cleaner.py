# ── pipeline/cleaner.py ───────────────────────────────────────────────────────
# Data cleaner — the first stage of the pipeline.
#
# What does the cleaner do?
#   Takes raw scraped dicts straight from the parser and normalizes them.
#   Raw scraped data is always messy — extra whitespace, inconsistent
#   encoding, None values mixed with empty strings, HTML entities left
#   in text, prices with currency symbols, numbers as strings.
#   The cleaner fixes all of this before any business logic runs.
#
# Pipeline position:
#   Parser → [Cleaner] → Transformer → Validator → Storage
#
# Rule: the cleaner never REMOVES fields and never changes field names.
#   It only normalizes values. Removing fields is the transformer's job.
#   Renaming fields is the transformer's job.
#   The cleaner just makes values consistent and usable.

import re
import html as html_module             # Python's built-in HTML entity decoder
from typing import Any, Optional
from utils.logger import log


class DataCleaner:
    """
    Cleans raw scraped data by normalizing field values.

    Used by calling clean_item() on each dict from the parser,
    or clean_items() on a full list.

    Example:
        cleaner = DataCleaner()
        raw = {"title": "  Book Title\\n", "price": "Â£9.99", "stock": None}
        clean = cleaner.clean_item(raw)
        # → {"title": "Book Title", "price": "£9.99", "stock": ""}
    """

    def clean_item(self, item: dict) -> dict:
        """
        Cleans a single scraped dict by applying all cleaning rules to each value.

        Applies in order:
        1. None → empty string (no None values in output)
        2. Whitespace normalization
        3. HTML entity decoding
        4. Unicode normalization
        5. Type-specific cleaning (prices, numbers, URLs)

        Args:
            item: raw dict from the parser

        Returns:
            cleaned dict with same keys, normalized values
        """
        if not item:
            return {}

        cleaned = {}
        for key, value in item.items():
            cleaned[key] = self._clean_value(key, value)

        return cleaned

    def clean_items(self, items: list[dict]) -> list[dict]:
        """
        Cleans a list of scraped dicts.
        Skips None or empty items, logs how many were cleaned.

        Args:
            items: list of raw dicts from the parser

        Returns:
            list of cleaned dicts
        """
        if not items:
            return []

        cleaned = [self.clean_item(item) for item in items if item]
        log.debug("DataCleaner: cleaned {} items", len(cleaned))
        return cleaned

    def _clean_value(self, key: str, value: Any) -> Any:
        """
        Routes a value to the appropriate cleaning method based on its type
        and key name. Key-based routing allows price fields to be cleaned
        differently from title fields, for example.

        Args:
            key:   the field name — used to apply field-specific rules
            value: the raw value to clean

        Returns:
            cleaned value
        """
        # None becomes empty string — no None values in the pipeline
        if value is None:
            return ""

        # Lists — clean each element recursively
        if isinstance(value, list):
            return [self._clean_value(key, v) for v in value]

        # Dicts — clean each value recursively
        if isinstance(value, dict):
            return {k: self._clean_value(k, v) for k, v in value.items()}

        # Booleans — return as-is, don't convert to string
        if isinstance(value, bool):
            return value

        # Numbers — return as-is
        if isinstance(value, (int, float)):
            return value

        # Strings — apply full cleaning pipeline
        if isinstance(value, str):
            return self._clean_string(key, value)

        # Everything else — convert to string and clean
        return self._clean_string(key, str(value))

    def _clean_string(self, key: str, value: str) -> str:
        """
        Applies the full string cleaning pipeline to a single value.

        Steps:
        1. Decode HTML entities (&amp; → &, &lt; → <, Â£ → £)
        2. Normalize unicode (fix encoding artifacts)
        3. Strip and collapse whitespace
        4. Apply key-specific rules (price, url, etc.)
        """
        if not value:
            return ""

        # Step 1 — decode HTML entities
        # &amp; → &, &lt; → <, &gt; → >, &nbsp; → space, Â£ → £
        value = html_module.unescape(value)

        # Step 2 — fix common encoding artifacts
        # Â£ is £ mangled by wrong encoding (latin-1 read as utf-8)
        value = self._fix_encoding(value)

        # Step 3 — normalize whitespace
        # Strip leading/trailing, collapse internal spaces/tabs/newlines
        value = re.sub(r"\s+", " ", value).strip()

        # Step 4 — key-specific cleaning
        key_lower = key.lower()

        if any(word in key_lower for word in ["price", "cost", "amount", "fee"]):
            value = self._clean_price(value)

        elif any(word in key_lower for word in ["url", "link", "href", "src", "image"]):
            value = self._clean_url(value)

        elif any(word in key_lower for word in ["phone", "tel", "mobile"]):
            value = self._clean_phone(value)

        return value

    def _fix_encoding(self, value: str) -> str:
        """
        Fixes common encoding artifacts that appear when a site's encoding
        is misread. The most common is Â£ appearing instead of £.

        This happens when UTF-8 encoded text is read as latin-1:
        £ in UTF-8 is bytes 0xC2 0xA3 → misread as Â (0xC2) + £ (0xA3)

        We try to re-encode as latin-1 and decode as utf-8 to fix this.
        """
        try:
            # Attempt to fix mojibake (garbled unicode)
            fixed = value.encode("latin-1").decode("utf-8")
            return fixed
        except (UnicodeEncodeError, UnicodeDecodeError):
            # Value is already correct unicode — return unchanged
            return value

    def _clean_price(self, value: str) -> str:
        """
        Normalizes price strings to a consistent format.

        Examples:
            "Â£9.99"     → "£9.99"
            "  $14.99 "  → "$14.99"
            "USD 29.99"  → "USD 29.99"
            "9,99"       → "9.99"   (European decimal comma)
        """
        # Normalize European decimal comma to period
        # Only do this if there's exactly one comma and it looks like a decimal
        # e.g. "9,99" → "9.99" but NOT "1,000.00" → leave as-is
        if re.match(r"^\D*\d+,\d{2}\D*$", value):
            value = value.replace(",", ".")

        return value.strip()

    def _clean_url(self, value: str) -> str:
        """
        Normalizes URL strings — strips whitespace, removes line breaks
        that sometimes appear in scraped href attributes.
        """
        return value.strip().replace("\n", "").replace("\t", "")

    def _clean_phone(self, value: str) -> str:
        """
        Normalizes phone numbers to digits-only with optional + prefix.

        Examples:
            "(+234) 080-1234-5678" → "+2348012345678"
            "080 123 4567"          → "0801234567"
        """
        # Keep digits and leading +
        digits = re.sub(r"[^\d+]", "", value)
        return digits

    # ── Convenience static methods ────────────────────────────────────────────

    @staticmethod
    def strip_html_tags(text: str) -> str:
        """
        Removes all HTML tags from a string.
        Useful when a field contains inline HTML that wasn't stripped by the parser.

        Example:
            strip_html_tags("<b>Bold</b> and <i>italic</i>") → "Bold and italic"
        """
        return re.sub(r"<[^>]+>", "", text).strip()

    @staticmethod
    def extract_number(text: str) -> Optional[float]:
        """
        Extracts the first number from a string.
        Returns None if no number found.

        Examples:
            extract_number("$9.99")          → 9.99
            extract_number("In stock (22)")  → 22.0
            extract_number("No numbers")     → None
        """
        match = re.search(r"[\d,]+\.?\d*", text)
        if match:
            try:
                return float(match.group().replace(",", ""))
            except ValueError:
                return None
        return None

    @staticmethod
    def normalize_whitespace(text: str) -> str:
        """
        Collapses all whitespace sequences to a single space and strips edges.
        Standalone utility — same logic used internally by _clean_string.
        """
        return re.sub(r"\s+", " ", text).strip()
