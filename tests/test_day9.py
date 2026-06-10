# ── tests/test_day9.py ────────────────────────────────────────────────────────
# Isolation tests for Day 9: DataFrameBuilder, DataAnalyzer, DataExporter
# Run with: pytest tests/test_day9.py -v

import pytest
import pandas as pd
import numpy as np
import os


# ── Shared fixtures ───────────────────────────────────────────────────────────

SAMPLE_ITEMS = [
    {"title": "Book A", "price": 9.99,  "url": "https://example.com/1", "rating": "Three"},
    {"title": "Book B", "price": 14.99, "url": "https://example.com/2", "rating": "One"},
    {"title": "Book C", "price": 7.49,  "url": "https://example.com/3", "rating": "Five"},
    {"title": "Book D", "price": 9.99,  "url": "https://example.com/4", "rating": "Two"},
    {"title": "Book E", "price": 22.00, "url": "https://example.com/5", "rating": "Four"},
]

ITEMS_WITH_DUPES = SAMPLE_ITEMS + [
    {"title": "Book A", "price": 9.99, "url": "https://example.com/1", "rating": "Three"},  # exact dupe
]

ITEMS_WITH_NULLS = [
    {"title": "Book A", "price": None,  "url": "https://example.com/1"},
    {"title": None,     "price": 14.99, "url": "https://example.com/2"},
    {"title": "Book C", "price": 7.49,  "url": "https://example.com/3"},
]


# ── DataFrameBuilder Tests ────────────────────────────────────────────────────

class TestDataFrameBuilder:

    def test_builds_dataframe_from_items(self):
        from pandas_layer.dataframe_builder import DataFrameBuilder
        builder = DataFrameBuilder()
        df = builder.build(SAMPLE_ITEMS)
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 5

    def test_empty_items_returns_empty_df(self):
        from pandas_layer.dataframe_builder import DataFrameBuilder
        builder = DataFrameBuilder(columns=["title", "price"])
        df = builder.build([])
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0
        assert list(df.columns) == ["title", "price"]

    def test_column_order_enforced(self):
        from pandas_layer.dataframe_builder import DataFrameBuilder
        cols = ["url", "title", "price"]
        builder = DataFrameBuilder(columns=cols)
        df = builder.build(SAMPLE_ITEMS)
        assert list(df.columns) == cols

    def test_missing_column_added_as_nan(self):
        from pandas_layer.dataframe_builder import DataFrameBuilder
        cols = ["title", "price", "missing_col"]
        builder = DataFrameBuilder(columns=cols)
        df = builder.build(SAMPLE_ITEMS)
        assert "missing_col" in df.columns
        assert df["missing_col"].isna().all()

    def test_extra_columns_dropped(self):
        from pandas_layer.dataframe_builder import DataFrameBuilder
        cols = ["title", "price"]   # rating and url not included
        builder = DataFrameBuilder(columns=cols)
        df = builder.build(SAMPLE_ITEMS)
        assert "rating" not in df.columns
        assert "url" not in df.columns

    def test_dtype_cast_to_float(self):
        from pandas_layer.dataframe_builder import DataFrameBuilder
        items = [{"price": "9.99"}, {"price": "14.99"}]
        builder = DataFrameBuilder(dtypes={"price": float})
        df = builder.build(items)
        assert df["price"].dtype in [np.float64, float]

    def test_dtype_cast_to_str(self):
        from pandas_layer.dataframe_builder import DataFrameBuilder
        builder = DataFrameBuilder(dtypes={"title": str})
        df = builder.build(SAMPLE_ITEMS)
        assert df["title"].dtype in [object, "string"] or "str" in str(df["title"].dtype)

    def test_fill_missing_defaults(self):
        from pandas_layer.dataframe_builder import DataFrameBuilder
        builder = DataFrameBuilder(
            columns=["title", "price", "missing_col"],
            fill_missing={"missing_col": "N/A"}
        )
        df = builder.build(SAMPLE_ITEMS)
        assert (df["missing_col"] == "N/A").all()

    def test_from_csv_returns_dataframe(self, tmp_path):
        from pandas_layer.dataframe_builder import DataFrameBuilder
        # Write a test CSV
        csv_path = str(tmp_path / "test.csv")
        pd.DataFrame(SAMPLE_ITEMS).to_csv(csv_path, index=False)
        df = DataFrameBuilder.from_csv(csv_path)
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 5

    def test_from_csv_missing_file(self):
        from pandas_layer.dataframe_builder import DataFrameBuilder
        df = DataFrameBuilder.from_csv("nonexistent_file.csv")
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0

    def test_build_empty_returns_correct_columns(self):
        from pandas_layer.dataframe_builder import DataFrameBuilder
        builder = DataFrameBuilder(columns=["title", "price", "url"])
        df = builder.build_empty()
        assert list(df.columns) == ["title", "price", "url"]
        assert len(df) == 0


# ── DataAnalyzer Tests ────────────────────────────────────────────────────────

class TestDataAnalyzer:

    def test_analyze_returns_df_and_report(self):
        from pandas_layer.analyzer import DataAnalyzer, QualityReport
        analyzer = DataAnalyzer()
        df = pd.DataFrame(SAMPLE_ITEMS)
        result_df, report = analyzer.analyze(df)
        assert isinstance(result_df, pd.DataFrame)
        assert isinstance(report, QualityReport)

    def test_detects_duplicate_rows(self):
        from pandas_layer.analyzer import DataAnalyzer
        analyzer = DataAnalyzer()
        df = pd.DataFrame(ITEMS_WITH_DUPES)
        result_df, report = analyzer.analyze(df)
        assert report.duplicate_rows == 1
        assert len(result_df) == len(ITEMS_WITH_DUPES) - 1

    def test_dedup_on_specific_column(self):
        from pandas_layer.analyzer import DataAnalyzer
        analyzer = DataAnalyzer()
        df = pd.DataFrame(ITEMS_WITH_DUPES)
        result_df, report = analyzer.analyze(df, dedupe_columns=["url"])
        assert report.duplicate_rows == 1

    def test_null_counts_tracked(self):
        from pandas_layer.analyzer import DataAnalyzer
        analyzer = DataAnalyzer()
        df = pd.DataFrame(ITEMS_WITH_NULLS)
        _, report = analyzer.analyze(df)
        assert report.null_counts.get("price", 0) >= 1
        assert report.null_counts.get("title", 0) >= 1

    def test_required_column_null_flagged(self):
        from pandas_layer.analyzer import DataAnalyzer
        analyzer = DataAnalyzer()
        df = pd.DataFrame(ITEMS_WITH_NULLS)
        _, report = analyzer.analyze(df, required_columns=["title"])
        assert any("title" in issue for issue in report.issues)

    def test_perfect_data_scores_high(self):
        from pandas_layer.analyzer import DataAnalyzer
        analyzer = DataAnalyzer()
        df = pd.DataFrame(SAMPLE_ITEMS)
        _, report = analyzer.analyze(df)
        assert report.quality_score >= 0.9

    def test_empty_df_returns_full_score(self):
        from pandas_layer.analyzer import DataAnalyzer
        analyzer = DataAnalyzer()
        df = pd.DataFrame()
        result_df, report = analyzer.analyze(df)
        assert report.quality_score == 1.0
        assert report.total_rows == 0

    def test_summary_stats_numeric_cols(self):
        from pandas_layer.analyzer import DataAnalyzer
        analyzer = DataAnalyzer()
        df = pd.DataFrame(SAMPLE_ITEMS)
        stats = analyzer.summary_stats(df)
        assert isinstance(stats, pd.DataFrame)
        assert "price" in stats.columns

    def test_summary_stats_no_numeric(self):
        from pandas_layer.analyzer import DataAnalyzer
        analyzer = DataAnalyzer()
        df = pd.DataFrame([{"name": "A"}, {"name": "B"}])
        stats = analyzer.summary_stats(df)
        assert stats.empty

    def test_value_counts(self):
        from pandas_layer.analyzer import DataAnalyzer
        analyzer = DataAnalyzer()
        df = pd.DataFrame(SAMPLE_ITEMS)
        counts = analyzer.value_counts(df, "rating")
        assert isinstance(counts, pd.Series)
        assert len(counts) <= 5

    def test_value_counts_missing_column(self):
        from pandas_layer.analyzer import DataAnalyzer
        analyzer = DataAnalyzer()
        df = pd.DataFrame(SAMPLE_ITEMS)
        counts = analyzer.value_counts(df, "nonexistent_column")
        assert isinstance(counts, pd.Series)
        assert len(counts) == 0

    def test_filter_by_quality_drops_null_rows(self):
        from pandas_layer.analyzer import DataAnalyzer
        analyzer = DataAnalyzer()
        df = pd.DataFrame(ITEMS_WITH_NULLS)
        filtered = analyzer.filter_by_quality(df, required_columns=["title", "price"])
        # Only Book C has both title and price — others have one null each
        assert len(filtered) == 1
        assert filtered.iloc[0]["title"] == "Book C"

    def test_quality_report_str(self):
        from pandas_layer.analyzer import QualityReport
        report = QualityReport(total_rows=10, duplicate_rows=2, quality_score=0.85)
        s = str(report)
        assert "10" in s
        assert "0.85" in s


# ── DataExporter Tests ────────────────────────────────────────────────────────

class TestDataExporter:

    def test_to_csv_creates_file(self, tmp_path):
        from pandas_layer.exporter import DataExporter
        exporter = DataExporter(output_dir=str(tmp_path))
        df = pd.DataFrame(SAMPLE_ITEMS)
        path = exporter.to_csv(df, "test_books", include_timestamp=False)
        assert os.path.exists(path)

    def test_to_csv_correct_row_count(self, tmp_path):
        from pandas_layer.exporter import DataExporter
        exporter = DataExporter(output_dir=str(tmp_path))
        df = pd.DataFrame(SAMPLE_ITEMS)
        path = exporter.to_csv(df, "test_books", include_timestamp=False)
        loaded = pd.read_csv(path)
        assert len(loaded) == len(SAMPLE_ITEMS)

    def test_to_csv_empty_df_returns_empty_string(self, tmp_path):
        from pandas_layer.exporter import DataExporter
        exporter = DataExporter(output_dir=str(tmp_path))
        df = pd.DataFrame()
        path = exporter.to_csv(df, "empty")
        assert path == ""

    def test_to_excel_creates_file(self, tmp_path):
        from pandas_layer.exporter import DataExporter
        exporter = DataExporter(output_dir=str(tmp_path))
        df = pd.DataFrame(SAMPLE_ITEMS)
        path = exporter.to_excel(df, "test_books", include_timestamp=False)
        assert os.path.exists(path)
        assert path.endswith(".xlsx")

    def test_to_excel_correct_row_count(self, tmp_path):
        from pandas_layer.exporter import DataExporter
        exporter = DataExporter(output_dir=str(tmp_path))
        df = pd.DataFrame(SAMPLE_ITEMS)
        path = exporter.to_excel(df, "test_books", include_timestamp=False)
        loaded = pd.read_excel(path)
        assert len(loaded) == len(SAMPLE_ITEMS)

    def test_to_json_creates_file(self, tmp_path):
        from pandas_layer.exporter import DataExporter
        exporter = DataExporter(output_dir=str(tmp_path))
        df = pd.DataFrame(SAMPLE_ITEMS)
        path = exporter.to_json(df, "test_books", include_timestamp=False)
        assert os.path.exists(path)
        assert path.endswith(".json")

    def test_to_json_valid_json(self, tmp_path):
        from pandas_layer.exporter import DataExporter
        import json
        exporter = DataExporter(output_dir=str(tmp_path))
        df = pd.DataFrame(SAMPLE_ITEMS)
        path = exporter.to_json(df, "test_books", include_timestamp=False)
        with open(path) as f:
            data = json.load(f)
        assert isinstance(data, list)
        assert len(data) == len(SAMPLE_ITEMS)

    def test_to_all_multiple_formats(self, tmp_path):
        from pandas_layer.exporter import DataExporter
        exporter = DataExporter(output_dir=str(tmp_path))
        df = pd.DataFrame(SAMPLE_ITEMS)
        paths = exporter.to_all(df, "test_books", formats=["csv", "json"])
        assert "csv" in paths
        assert "json" in paths
        assert os.path.exists(paths["csv"])
        assert os.path.exists(paths["json"])

    def test_df_to_records_static(self):
        from pandas_layer.exporter import DataExporter
        df = pd.DataFrame(SAMPLE_ITEMS)
        records = DataExporter.df_to_records(df)
        assert isinstance(records, list)
        assert len(records) == len(SAMPLE_ITEMS)
        assert isinstance(records[0], dict)

    def test_df_to_records_nan_becomes_none(self):
        from pandas_layer.exporter import DataExporter
        df = pd.DataFrame([{"title": "Book", "price": np.nan}])
        records = DataExporter.df_to_records(df)
        assert records[0]["price"] is None

    def test_timestamp_in_filename(self, tmp_path):
        from pandas_layer.exporter import DataExporter
        exporter = DataExporter(output_dir=str(tmp_path))
        df = pd.DataFrame(SAMPLE_ITEMS)
        path = exporter.to_csv(df, "books", include_timestamp=True)
        # filename should contain date pattern
        assert "books_2" in path   # "books_2026..." or similar year
