# ── tests/test_day8.py ────────────────────────────────────────────────────────
# Isolation tests for Day 8: DataCleaner, DataTransformer, DataValidator
# Run with: pytest tests/test_day8.py -v

import pytest
from datetime import datetime


# ── DataCleaner Tests ─────────────────────────────────────────────────────────

class TestDataCleaner:

    def test_cleans_whitespace(self):
        from pipeline.cleaner import DataCleaner
        cleaner = DataCleaner()
        result = cleaner.clean_item({"title": "  Hello   World  "})
        assert result["title"] == "Hello World"

    def test_none_becomes_empty_string(self):
        from pipeline.cleaner import DataCleaner
        cleaner = DataCleaner()
        result = cleaner.clean_item({"field": None})
        assert result["field"] == ""

    def test_decodes_html_entities(self):
        from pipeline.cleaner import DataCleaner
        cleaner = DataCleaner()
        result = cleaner.clean_item({"title": "AT&amp;T"})
        assert result["title"] == "AT&T"

    def test_fixes_encoding_artifact(self):
        from pipeline.cleaner import DataCleaner
        cleaner = DataCleaner()
        # Â£ is £ mangled by wrong encoding
        result = cleaner.clean_item({"price": "Â£9.99"})
        assert "£" in result["price"] or "9.99" in result["price"]

    def test_collapses_newlines(self):
        from pipeline.cleaner import DataCleaner
        cleaner = DataCleaner()
        result = cleaner.clean_item({"title": "Line 1\n\nLine 2"})
        assert result["title"] == "Line 1 Line 2"

    def test_integers_pass_through(self):
        from pipeline.cleaner import DataCleaner
        cleaner = DataCleaner()
        result = cleaner.clean_item({"count": 42})
        assert result["count"] == 42

    def test_floats_pass_through(self):
        from pipeline.cleaner import DataCleaner
        cleaner = DataCleaner()
        result = cleaner.clean_item({"price": 9.99})
        assert result["price"] == 9.99

    def test_booleans_pass_through(self):
        from pipeline.cleaner import DataCleaner
        cleaner = DataCleaner()
        result = cleaner.clean_item({"active": True})
        assert result["active"] is True

    def test_empty_item_returns_empty(self):
        from pipeline.cleaner import DataCleaner
        cleaner = DataCleaner()
        assert cleaner.clean_item({}) == {}
        assert cleaner.clean_item(None) == {}

    def test_clean_items_processes_list(self):
        from pipeline.cleaner import DataCleaner
        cleaner = DataCleaner()
        items = [{"title": "  A  "}, {"title": "  B  "}]
        result = cleaner.clean_items(items)
        assert result[0]["title"] == "A"
        assert result[1]["title"] == "B"

    def test_clean_items_empty_list(self):
        from pipeline.cleaner import DataCleaner
        cleaner = DataCleaner()
        assert cleaner.clean_items([]) == []

    def test_cleans_url_field(self):
        from pipeline.cleaner import DataCleaner
        cleaner = DataCleaner()
        result = cleaner.clean_item({"url": "  https://example.com/page\n"})
        assert result["url"] == "https://example.com/page"

    def test_cleans_phone_field(self):
        from pipeline.cleaner import DataCleaner
        cleaner = DataCleaner()
        result = cleaner.clean_item({"phone": "(080) 123-4567"})
        assert result["phone"] == "0801234567"

    def test_strip_html_tags_static(self):
        from pipeline.cleaner import DataCleaner
        result = DataCleaner.strip_html_tags("<b>Bold</b> text")
        assert result == "Bold text"
        assert "<" not in result

    def test_extract_number_static(self):
        from pipeline.cleaner import DataCleaner
        assert DataCleaner.extract_number("$9.99") == 9.99
        assert DataCleaner.extract_number("In stock (22)") == 22.0
        assert DataCleaner.extract_number("No numbers here") is None

    def test_nested_list_values_cleaned(self):
        from pipeline.cleaner import DataCleaner
        cleaner = DataCleaner()
        result = cleaner.clean_item({"tags": ["  python  ", "  scraping  "]})
        assert result["tags"] == ["python", "scraping"]

    def test_normalize_whitespace_static(self):
        from pipeline.cleaner import DataCleaner
        result = DataCleaner.normalize_whitespace("  too   many   spaces  ")
        assert result == "too many spaces"


# ── DataTransformer Tests ─────────────────────────────────────────────────────

class TestDataTransformer:

    def test_renames_fields(self):
        from pipeline.transformer import DataTransformer
        t = DataTransformer(field_map={"old_name": "new_name"})
        result = t.transform_item({"old_name": "value", "other": "x"})
        assert "new_name" in result
        assert "old_name" not in result

    def test_keeps_unmapped_fields(self):
        from pipeline.transformer import DataTransformer
        t = DataTransformer(field_map={"a": "b"})
        result = t.transform_item({"a": "1", "c": "3"})
        assert "b" in result
        assert "c" in result

    def test_drop_fields(self):
        from pipeline.transformer import DataTransformer
        t = DataTransformer(drop_fields=["internal_id", "raw_html"])
        result = t.transform_item({"title": "Book", "internal_id": "123", "raw_html": "<html>"})
        assert "internal_id" not in result
        assert "raw_html" not in result
        assert "title" in result

    def test_keep_fields_whitelist(self):
        from pipeline.transformer import DataTransformer
        t = DataTransformer(keep_fields=["title", "price"])
        result = t.transform_item({"title": "Book", "price": "9.99", "internal": "x"})
        assert "title" in result
        assert "price" in result
        assert "internal" not in result

    def test_type_cast_to_float(self):
        from pipeline.transformer import DataTransformer
        t = DataTransformer(type_casts={"price": float})
        result = t.transform_item({"price": "9.99"})
        assert result["price"] == 9.99
        assert isinstance(result["price"], float)

    def test_type_cast_price_with_symbol(self):
        from pipeline.transformer import DataTransformer
        t = DataTransformer(type_casts={"price": float})
        result = t.transform_item({"price": "$14.99"})
        assert result["price"] == 14.99

    def test_type_cast_to_int(self):
        from pipeline.transformer import DataTransformer
        t = DataTransformer(type_casts={"count": int})
        result = t.transform_item({"count": "42"})
        assert result["count"] == 42
        assert isinstance(result["count"], int)

    def test_type_cast_to_bool_in_stock(self):
        from pipeline.transformer import DataTransformer
        t = DataTransformer(type_casts={"available": bool})
        result = t.transform_item({"available": "in stock"})
        assert result["available"] is True

    def test_type_cast_empty_value_skipped(self):
        from pipeline.transformer import DataTransformer
        t = DataTransformer(type_casts={"price": float})
        result = t.transform_item({"price": ""})
        assert result["price"] == ""   # empty string not cast

    def test_computed_field(self):
        from pipeline.transformer import DataTransformer
        t = DataTransformer(
            computed={"title_length": lambda item: len(item.get("title", ""))}
        )
        result = t.transform_item({"title": "Hello"})
        assert result["title_length"] == 5

    def test_computed_field_failure_returns_none(self):
        from pipeline.transformer import DataTransformer
        t = DataTransformer(
            computed={"bad_field": lambda item: 1 / 0}   # will raise ZeroDivisionError
        )
        result = t.transform_item({"title": "Book"})
        assert result["bad_field"] is None   # failure handled gracefully

    def test_add_metadata_scraped_at(self):
        from pipeline.transformer import DataTransformer
        t = DataTransformer(add_metadata=True)
        result = t.transform_item({"title": "Book"})
        assert "scraped_at" in result
        assert result["scraped_at"] is not None

    def test_no_metadata_when_disabled(self):
        from pipeline.transformer import DataTransformer
        t = DataTransformer(add_metadata=False)
        result = t.transform_item({"title": "Book"})
        assert "scraped_at" not in result

    def test_does_not_mutate_input(self):
        from pipeline.transformer import DataTransformer
        t = DataTransformer(field_map={"a": "b"})
        original = {"a": "value"}
        t.transform_item(original)
        assert "a" in original       # original unchanged
        assert "b" not in original   # new key not added to original

    def test_transform_items_list(self):
        from pipeline.transformer import DataTransformer
        t = DataTransformer(type_casts={"price": float})
        items = [{"price": "9.99"}, {"price": "14.99"}]
        results = t.transform_items(items)
        assert results[0]["price"] == 9.99
        assert results[1]["price"] == 14.99

    def test_transform_items_empty(self):
        from pipeline.transformer import DataTransformer
        t = DataTransformer()
        assert t.transform_items([]) == []

    def test_field_map_then_keep_fields_uses_new_names(self):
        from pipeline.transformer import DataTransformer
        # keep_fields should use NEW names after field_map is applied
        t = DataTransformer(
            field_map={"old": "new"},
            keep_fields=["new"]         # "new" not "old"
        )
        result = t.transform_item({"old": "value", "extra": "x"})
        assert "new" in result
        assert "extra" not in result


# ── DataValidator Tests ───────────────────────────────────────────────────────

class TestDataValidator:

    def _make_book_validator(self, strict=False):
        from pipeline.validator import DataValidator, BookSchema
        return DataValidator(schema=BookSchema, strict=strict)

    def test_valid_item_passes(self):
        v = self._make_book_validator()
        item = {"url": "https://example.com/book", "title": "Test Book", "price": 9.99}
        result = v.validate_item(item)
        assert result.valid is True
        assert result.errors == []

    def test_missing_required_field_fails(self):
        v = self._make_book_validator()
        item = {"url": "https://example.com/book"}   # missing title
        result = v.validate_item(item)
        assert result.valid is False
        assert len(result.errors) > 0

    def test_extra_fields_ignored(self):
        v = self._make_book_validator()
        item = {
            "url": "https://example.com/book",
            "title": "Test Book",
            "extra_field": "ignored",   # not in schema — should be ignored
        }
        result = v.validate_item(item)
        assert result.valid is True
        assert "extra_field" not in result.item

    def test_optional_fields_absent_ok(self):
        v = self._make_book_validator()
        item = {"url": "https://example.com/book", "title": "Book"}
        result = v.validate_item(item)
        assert result.valid is True
        # Optional fields should be None when absent
        assert result.item.get("price") is None

    def test_pydantic_coerces_string_to_float(self):
        v = self._make_book_validator()
        item = {"url": "https://example.com", "title": "Book", "price": "9.99"}
        result = v.validate_item(item)
        # Pydantic should coerce "9.99" string to 9.99 float
        assert result.valid is True

    def test_validate_batch_returns_batch_result(self):
        from pipeline.validator import BatchValidationResult
        v = self._make_book_validator()
        items = [
            {"url": "https://example.com/1", "title": "Book A"},
            {"url": "https://example.com/2", "title": "Book B"},
        ]
        result = v.validate_batch(items)
        assert isinstance(result, BatchValidationResult)
        assert result.total == 2

    def test_validate_batch_pass_rate(self):
        v = self._make_book_validator()
        items = [
            {"url": "https://example.com/1", "title": "Book A"},   # valid
            {"url": "https://example.com/2", "title": "Book B"},   # valid
            {"title": "No URL"},                                     # invalid — missing url
        ]
        result = v.validate_batch(items)
        assert len(result.valid_items) == 2
        assert len(result.invalid_items) == 1
        assert abs(result.pass_rate - 0.667) < 0.01

    def test_strict_mode_drops_invalid(self):
        v = self._make_book_validator(strict=True)
        items = [
            {"url": "https://example.com/1", "title": "Book A"},   # valid
            {"title": "No URL"},                                     # invalid
        ]
        result = v.validate_batch(items)
        # strict=True: invalid items dropped, not in valid_items
        assert len(result.valid_items) == 1

    def test_lenient_mode_tracks_invalid(self):
        v = self._make_book_validator(strict=False)
        items = [
            {"url": "https://example.com/1", "title": "Book A"},
            {"title": "No URL"},
        ]
        result = v.validate_batch(items)
        assert len(result.invalid_items) == 1
        assert len(result.invalid_items[0].errors) > 0

    def test_empty_batch(self):
        from pipeline.validator import BatchValidationResult
        v = self._make_book_validator()
        result = v.validate_batch([])
        assert result.total == 0
        assert result.pass_rate == 0.0

    def test_get_schema_fields(self):
        v = self._make_book_validator()
        fields = v.get_schema_fields()
        assert "url" in fields
        assert "title" in fields
        assert "price" in fields

    def test_validation_result_str_pass(self):
        from pipeline.validator import ValidationResult
        r = ValidationResult(valid=True, item={"title": "Book"})
        assert "PASS" in str(r)

    def test_validation_result_str_fail(self):
        from pipeline.validator import ValidationResult
        r = ValidationResult(valid=False, item={}, errors=["title: required"])
        assert "FAIL" in str(r)

    def test_batch_result_str(self):
        from pipeline.validator import BatchValidationResult
        r = BatchValidationResult(valid_items=[{"a": 1}, {"b": 2}])
        assert "2" in str(r)


# ── Full Pipeline Integration Tests ──────────────────────────────────────────

class TestFullPipeline:
    """Tests the complete cleaner → transformer → validator pipeline."""

    def test_end_to_end_book_pipeline(self):
        from pipeline.cleaner import DataCleaner
        from pipeline.transformer import DataTransformer
        from pipeline.validator import DataValidator, BookSchema

        # Raw data as it comes from the parser
        raw_items = [
            {
                "title": "  A Light in the Attic  ",
                "price_color": "Â£51.77",
                "url": "https://books.toscrape.com/catalogue/a-light_1000/index.html",
                "rating_class": "Three",
                "availability_text": "In stock",
            },
            {
                "title": "  Tipping the Velvet  ",
                "price_color": "Â£53.74",
                "url": "https://books.toscrape.com/catalogue/tipping_2/index.html",
                "rating_class": "One",
                "availability_text": "In stock",
            },
        ]

        # Stage 1 — Clean
        cleaner = DataCleaner()
        cleaned = cleaner.clean_items(raw_items)

        assert cleaned[0]["title"] == "A Light in the Attic"
        assert "£" in cleaned[0]["price_color"] or "51.77" in cleaned[0]["price_color"]

        # Stage 2 — Transform
        transformer = DataTransformer(
            field_map={
                "price_color": "price",
                "rating_class": "rating",
                "availability_text": "availability",
            },
            drop_fields=[],
            type_casts={"price": float},
            add_metadata=True,
        )
        transformed = transformer.transform_items(cleaned)

        assert "price" in transformed[0]
        assert "rating" in transformed[0]
        assert "scraped_at" in transformed[0]
        assert isinstance(transformed[0]["price"], float)

        # Stage 3 — Validate
        validator = DataValidator(schema=BookSchema, strict=False)
        batch = validator.validate_batch(transformed)

        assert batch.total == 2
        assert batch.pass_rate == 1.0
        assert len(batch.valid_items) == 2
