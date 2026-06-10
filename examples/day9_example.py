# ── examples/day9_example.py ──────────────────────────────────────────────────
# Day 9 mini example — full pandas layer demo on real scraped data.
# Builds a DataFrame, analyzes quality, exports to CSV/Excel/JSON.
#
# Run with: python examples/day9_example.py

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.logger import log
from utils.helpers import ensure_dir
from fetcher.http_fetcher import HttpFetcher
from parser.bs4_parser import BS4Parser
from pipeline.cleaner import DataCleaner
from pipeline.transformer import DataTransformer
from pipeline.validator import DataValidator, BookSchema
from pandas_layer.dataframe_builder import DataFrameBuilder
from pandas_layer.analyzer import DataAnalyzer
from pandas_layer.exporter import DataExporter


def main():
    ensure_dir("logs")
    ensure_dir("data")

    log.info("=" * 60)
    log.info("Day 9 — Pandas Layer Demo")
    log.info("=" * 60)

    # ── Fetch and run through pipeline first ─────────────────────────────────
    log.info("Fetching and parsing books data...")

    with HttpFetcher() as fetcher:
        result = fetcher.fetch("https://books.toscrape.com/catalogue/page-1.html")

    parser = BS4Parser()
    soup = parser.make_soup(result.html)

    titles   = parser.get_all_text(soup, "h3 > a")
    prices   = parser.get_all_text(soup, "p.price_color")
    ratings  = parser.get_all_attr(soup, "p.star-rating", "class")
    avails   = parser.get_all_text(soup, "p.availability")
    links    = parser.get_all_attr(soup, "h3 > a", "href")

    raw_items = [
        {
            "title": t, "price_raw": p,
            "rating": " ".join(r) if isinstance(r, list) else r,
            "availability": a,
            "url": f"https://books.toscrape.com/catalogue/{l.replace('../', '')}",
        }
        for t, p, r, a, l in zip(titles, prices, ratings, avails, links)
    ]

    # Full pipeline
    cleaner = DataCleaner()
    transformer = DataTransformer(
        computed={"price": lambda item: DataCleaner.extract_number(item.get("price_raw", "") or "")},
        drop_fields=[],
        add_metadata=True,
    )
    validator = DataValidator(schema=BookSchema, strict=False)

    cleaned   = cleaner.clean_items(raw_items)
    transformed = transformer.transform_items(cleaned)
    batch     = validator.validate_batch(transformed)

    log.info("Pipeline output: {} valid items", len(batch.valid_items))

    # ── 1. DataFrameBuilder ───────────────────────────────────────────────────
    log.info("1. DataFrameBuilder — building DataFrame from validated items:")

    builder = DataFrameBuilder(
        columns=["title", "price", "rating", "availability", "url", "scraped_at"],
        dtypes={"price": float, "title": str},
        fill_missing={"rating": "Unknown", "availability": "Unknown"},
    )

    df = builder.build(batch.valid_items)

    log.info("  Shape: {} rows × {} columns", *df.shape)
    log.info("  Columns: {}", list(df.columns))
    log.info("  Dtypes:\n{}", df.dtypes.to_string())
    log.info("  First 3 rows:")
    for _, row in df.head(3).iterrows():
        log.info("    {} | £{} | {}", row["title"][:35], row["price"], row["availability"].strip())

    # ── 2. DataAnalyzer — quality checks ─────────────────────────────────────
    log.info("2. DataAnalyzer — running quality analysis:")

    analyzer = DataAnalyzer()
    df_clean, report = analyzer.analyze(
        df,
        dedupe_columns=["url"],
        required_columns=["title", "url"],
    )

    log.info("  Report: {}", report)
    log.info("  Quality score: {}", report.quality_score)
    log.info("  Duplicate rows: {}", report.duplicate_rows)
    log.info("  Null counts: {}", {k: v for k, v in report.null_counts.items() if v > 0})

    if report.issues:
        log.warning("  Issues found:")
        for issue in report.issues:
            log.warning("    - {}", issue)
    else:
        log.info("  No quality issues found")

    if report.recommendations:
        log.info("  Recommendations:")
        for rec in report.recommendations:
            log.info("    → {}", rec)

    # ── 3. Summary statistics ─────────────────────────────────────────────────
    log.info("3. Summary statistics for numeric columns:")
    stats = analyzer.summary_stats(df_clean)
    if not stats.empty:
        log.info("  Price stats:")
        log.info("    min={} max={} mean={:.2f} std={:.2f}",
                 stats.loc["min", "price"],
                 stats.loc["max", "price"],
                 stats.loc["mean", "price"],
                 stats.loc["std", "price"])

    # ── 4. Value counts ───────────────────────────────────────────────────────
    log.info("4. Rating distribution:")
    rating_counts = analyzer.value_counts(df_clean, "rating")
    for rating, count in rating_counts.items():
        log.info("  {}: {} books", rating, count)

    # ── 5. Filter by quality ──────────────────────────────────────────────────
    log.info("5. Filtering rows with missing required fields:")
    df_filtered = analyzer.filter_by_quality(df_clean, required_columns=["title", "price"])
    log.info("  Before filter: {} rows | After filter: {} rows",
             len(df_clean), len(df_filtered))

    # ── 6. DataExporter — export to all formats ───────────────────────────────
    log.info("6. DataExporter — exporting to CSV, Excel, JSON:")

    exporter = DataExporter(output_dir="data/")

    csv_path   = exporter.to_csv(df_filtered, "books_day9", include_timestamp=False)
    excel_path = exporter.to_excel(df_filtered, "books_day9", include_timestamp=False)
    json_path  = exporter.to_json(df_filtered, "books_day9", include_timestamp=False)

    log.info("  CSV:   {}", csv_path)
    log.info("  Excel: {}", excel_path)
    log.info("  JSON:  {}", json_path)

    # ── 7. Round-trip verification ────────────────────────────────────────────
    log.info("7. Round-trip — reload CSV and verify:")

    df_reloaded = DataFrameBuilder.from_csv(csv_path)
    log.info("  Reloaded {} rows from CSV", len(df_reloaded))
    log.info("  Columns match: {}", list(df_reloaded.columns) == list(df_filtered.columns))

    # ── 8. df_to_records — back to list of dicts for storage layer ────────────
    log.info("8. Converting DataFrame back to records for storage layer:")

    records = DataExporter.df_to_records(df_filtered)
    log.info("  {} records ready for storage", len(records))
    log.info("  Sample record keys: {}", list(records[0].keys()) if records else [])
    log.info("  NaN values: {}",
             any(v != v for rec in records for v in rec.values()))   # NaN != NaN

    log.info("=" * 60)
    log.success("Day 9 complete — pandas layer fully working")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
