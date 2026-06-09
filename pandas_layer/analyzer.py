# ── pandas_layer/analyzer.py ─────────────────────────────────────────────────
# DataFrame analysis — quality checks, deduplication, and summary stats.
#
# What does the analyzer do?
#   Takes a DataFrame from the builder and runs data quality operations:
#   - Deduplication (remove exact or near-duplicate rows)
#   - Null/missing value detection and reporting
#   - Summary statistics for numeric columns
#   - Schema drift detection (unexpected columns or missing expected ones)
#   - Data quality scoring
#
# This runs BEFORE exporting or saving to storage.
# Catching quality issues here is much cheaper than finding them in production.

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Optional
from utils.logger import log


@dataclass
class QualityReport:
    """
    Summary of data quality checks run on a DataFrame.

    Fields:
        total_rows:        how many rows in the DataFrame
        duplicate_rows:    how many exact duplicate rows found
        null_counts:       dict of column → null count
        quality_score:     0.0-1.0 overall quality (1.0 = perfect)
        issues:            list of human-readable issue descriptions
        recommendations:   list of suggested fixes
    """
    total_rows: int = 0
    duplicate_rows: int = 0
    null_counts: dict = field(default_factory=dict)
    quality_score: float = 1.0
    issues: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"QualityReport: {self.total_rows} rows | "
            f"{self.duplicate_rows} dupes | "
            f"score={self.quality_score:.2f} | "
            f"{len(self.issues)} issues"
        )


class DataAnalyzer:
    """
    Runs data quality analysis and transformations on a Pandas DataFrame.

    Usage:
        analyzer = DataAnalyzer()
        df, report = analyzer.analyze(df)
        print(report)
    """

    def analyze(
        self,
        df: pd.DataFrame,
        dedupe_columns: list[str] = None,
        required_columns: list[str] = None,
        max_null_rate: float = 0.5,
    ) -> tuple[pd.DataFrame, QualityReport]:
        """
        Runs the full analysis pipeline on a DataFrame.

        Steps:
        1. Basic shape and null check
        2. Deduplication
        3. Null rate analysis
        4. Schema check (missing/unexpected columns)
        5. Quality score calculation
        6. Return cleaned DataFrame + report

        Args:
            df:               DataFrame to analyze
            dedupe_columns:   columns to use for deduplication (None = all columns)
            required_columns: columns that must be present and non-null
            max_null_rate:    flag columns where null rate exceeds this threshold

        Returns:
            tuple of (cleaned DataFrame, QualityReport)
        """
        if df.empty:
            log.info("DataAnalyzer: empty DataFrame — skipping analysis")
            return df, QualityReport(total_rows=0, quality_score=1.0)

        report = QualityReport(total_rows=len(df))
        df = df.copy()   # never mutate the input DataFrame

        # Step 1 — deduplicate
        df, dupes = self._deduplicate(df, dedupe_columns)
        report.duplicate_rows = dupes

        # Step 2 — null analysis
        null_counts, null_issues = self._analyze_nulls(df, required_columns, max_null_rate)
        report.null_counts = null_counts
        report.issues.extend(null_issues)

        # Step 3 — schema check
        schema_issues = self._check_schema(df, required_columns)
        report.issues.extend(schema_issues)

        # Step 4 — calculate quality score
        report.quality_score = self._calculate_score(df, report)

        # Step 5 — generate recommendations
        report.recommendations = self._make_recommendations(report)

        log.info("DataAnalyzer: {}", report)
        return df, report

    def _deduplicate(
        self,
        df: pd.DataFrame,
        subset: list[str] = None,
    ) -> tuple[pd.DataFrame, int]:
        """
        Removes duplicate rows from the DataFrame.

        Args:
            df:     DataFrame to deduplicate
            subset: columns to consider for duplication check.
                    None means all columns must match for a row to be a duplicate.
                    Typically you'd use ["url"] or ["title", "price"] to dedupe
                    on the fields that uniquely identify a record.

        Returns:
            tuple of (deduplicated DataFrame, count of rows removed)
        """
        original_count = len(df)

        # keep="first" keeps the first occurrence and drops subsequent duplicates
        df = df.drop_duplicates(subset=subset, keep="first")

        removed = original_count - len(df)
        if removed > 0:
            log.info(
                "DataAnalyzer: removed {} duplicate rows (subset={})",
                removed, subset or "all columns"
            )

        return df, removed

    def _analyze_nulls(
        self,
        df: pd.DataFrame,
        required_columns: list[str] = None,
        max_null_rate: float = 0.5,
    ) -> tuple[dict, list[str]]:
        """
        Counts null values per column and flags columns with high null rates.

        Args:
            df:               DataFrame to check
            required_columns: these columns should never be null
            max_null_rate:    flag columns where null % exceeds this threshold

        Returns:
            tuple of (null_counts dict, list of issue strings)
        """
        # Count nulls per column — isnull() returns True for NaN/None/NaT
        null_counts = df.isnull().sum().to_dict()
        issues = []

        for col, null_count in null_counts.items():
            if null_count == 0:
                continue

            null_rate = null_count / len(df)

            # Flag required columns with any nulls
            if required_columns and col in required_columns and null_count > 0:
                issues.append(
                    f"Required column '{col}' has {null_count} null values"
                )

            # Flag columns with high null rates
            elif null_rate > max_null_rate:
                issues.append(
                    f"Column '{col}' has high null rate: "
                    f"{null_count}/{len(df)} ({null_rate:.1%})"
                )

        return null_counts, issues

    def _check_schema(
        self,
        df: pd.DataFrame,
        required_columns: list[str] = None,
    ) -> list[str]:
        """
        Checks for schema issues — missing required columns.

        Args:
            df:               DataFrame to check
            required_columns: columns that must be present

        Returns:
            list of schema issue strings
        """
        issues = []

        if required_columns:
            for col in required_columns:
                if col not in df.columns:
                    issues.append(f"Required column '{col}' is missing from DataFrame")

        return issues

    def _calculate_score(
        self,
        df: pd.DataFrame,
        report: QualityReport,
    ) -> float:
        """
        Calculates an overall data quality score between 0.0 and 1.0.

        Factors:
        - Duplicate rate (dupes / total rows)
        - Overall null rate (total nulls / total cells)
        - Number of issues found

        Score of 1.0 = perfect data, 0.0 = completely unusable.
        """
        if len(df) == 0:
            return 1.0

        # Duplicate penalty
        dupe_rate = report.duplicate_rows / (report.total_rows or 1)
        dupe_penalty = dupe_rate * 0.3   # dupes reduce score by up to 30%

        # Null penalty
        total_cells = df.size
        total_nulls = sum(report.null_counts.values())
        null_rate = total_nulls / total_cells if total_cells > 0 else 0
        null_penalty = null_rate * 0.4   # nulls reduce score by up to 40%

        # Issue penalty
        issue_penalty = min(len(report.issues) * 0.05, 0.3)  # max 30% for issues

        score = max(0.0, 1.0 - dupe_penalty - null_penalty - issue_penalty)
        return round(score, 3)

    def _make_recommendations(self, report: QualityReport) -> list[str]:
        """Generates human-readable recommendations based on report findings."""
        recs = []

        if report.duplicate_rows > 0:
            recs.append(
                f"Remove {report.duplicate_rows} duplicate rows before storage"
            )

        high_null_cols = [
            col for col, count in report.null_counts.items()
            if count > 0 and (count / (report.total_rows or 1)) > 0.3
        ]
        if high_null_cols:
            recs.append(
                f"Investigate null values in: {', '.join(high_null_cols)}"
            )

        if report.quality_score < 0.7:
            recs.append(
                "Quality score below 0.7 — review scraping selectors and pipeline"
            )

        return recs

    # ── Standalone utility methods ────────────────────────────────────────────

    def summary_stats(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Returns summary statistics for numeric columns.
        Equivalent to df.describe() but with better formatting and logging.

        Returns:
            DataFrame with count, mean, std, min, max for each numeric column
        """
        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        if not numeric_cols:
            log.info("DataAnalyzer: no numeric columns found for summary stats")
            return pd.DataFrame()

        stats = df[numeric_cols].describe().round(2)
        log.debug("DataAnalyzer: summary stats for {} numeric columns", len(numeric_cols))
        return stats

    def value_counts(self, df: pd.DataFrame, column: str, top_n: int = 10) -> pd.Series:
        """
        Returns the top N most common values in a column.
        Useful for checking categories, ratings, availability values.

        Args:
            df:     DataFrame to analyze
            column: column name to count
            top_n:  how many top values to return

        Returns:
            pd.Series with value → count mapping
        """
        if column not in df.columns:
            log.warning("DataAnalyzer: column '{}' not found", column)
            return pd.Series(dtype=int)

        return df[column].value_counts().head(top_n)

    def filter_by_quality(
        self,
        df: pd.DataFrame,
        required_columns: list[str],
        drop_nulls: bool = True,
    ) -> pd.DataFrame:
        """
        Filters out rows with null values in required columns.

        Args:
            df:               DataFrame to filter
            required_columns: rows with null in these columns are dropped
            drop_nulls:       if False, just logs but doesn't drop

        Returns:
            filtered DataFrame
        """
        if not required_columns:
            return df

        original_count = len(df)
        mask = df[required_columns].notna().all(axis=1)

        # axis=1 means check across columns for each row
        # notna() returns True for non-null values
        # all(axis=1) means all specified columns must be non-null

        if drop_nulls:
            df = df[mask]
            dropped = original_count - len(df)
            if dropped > 0:
                log.info(
                    "DataAnalyzer: dropped {} rows with nulls in {}",
                    dropped, required_columns
                )

        return df
