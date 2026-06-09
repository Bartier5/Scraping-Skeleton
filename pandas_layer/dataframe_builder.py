# ── pandas_layer/dataframe_builder.py ────────────────────────────────────────
# Converts validated pipeline output into a Pandas DataFrame.
#
# What does the DataFrame builder do?
#   Takes a list of clean dicts from the validator and builds a structured
#   DataFrame with enforced column types, column ordering, and schema
#   alignment. It's the entry point into the pandas layer.
#
# Why a dedicated builder instead of just pd.DataFrame(items)?
#   pd.DataFrame(items) works but gives you no guarantees:
#   - Columns appear in random order
#   - Mixed types in a column (int and None → object dtype)
#   - Missing columns silently absent
#   The builder enforces schema, handles missing columns, and sets
#   correct dtypes so the rest of the pandas layer works reliably.
#
# Pipeline position:
#   Validator → [DataFrameBuilder] → Analyzer → Exporter → Storage

import pandas as pd                    # core DataFrame library
import numpy as np                     # for NaN handling
from typing import Optional
from utils.logger import log


class DataFrameBuilder:
    """
    Builds a clean, schema-aligned Pandas DataFrame from validated dicts.

    Usage:
        builder = DataFrameBuilder(
            columns=["title", "price", "url", "scraped_at"],
            dtypes={"price": float, "title": str}
        )
        df = builder.build(validated_items)
    """

    def __init__(
        self,
        columns: list[str] = None,      # expected column order and set
        dtypes: dict[str, type] = None, # column → Python type mapping
        fill_missing: dict = None,      # default values for missing columns
    ):
        """
        Args:
            columns:      ordered list of expected column names.
                          If provided, DataFrame will have exactly these columns
                          in this order. Missing columns added as NaN.
                          Extra columns dropped.
            dtypes:       maps column names to target dtypes.
                          e.g. {"price": float, "title": str, "in_stock": bool}
            fill_missing: default values for specific columns when value is missing.
                          e.g. {"price": 0.0, "availability": "Unknown"}
        """
        self.columns = columns
        self.dtypes = dtypes or {}
        self.fill_missing = fill_missing or {}

        log.debug(
            "DataFrameBuilder initialized (columns={}, dtypes={})",
            len(columns) if columns else "auto",
            list(self.dtypes.keys()),
        )

    def build(self, items: list[dict]) -> pd.DataFrame:
        """
        Builds a DataFrame from a list of validated dicts.

        Steps:
        1. Create raw DataFrame from list of dicts
        2. Align columns (add missing, drop extra, reorder)
        3. Apply fill_missing defaults
        4. Apply dtype casting
        5. Return clean DataFrame

        Args:
            items: list of validated dicts from DataValidator

        Returns:
            pd.DataFrame with enforced schema
        """
        if not items:
            # Return an empty DataFrame with the right columns
            cols = self.columns or []
            log.info("DataFrameBuilder: empty items — returning empty DataFrame")
            return pd.DataFrame(columns=cols)

        # Step 1 — build raw DataFrame
        # pd.DataFrame(list_of_dicts) uses dict keys as columns
        df = pd.DataFrame(items)
        log.debug("DataFrameBuilder: raw DataFrame shape: {}", df.shape)

        # Step 2 — align columns if schema defined
        if self.columns:
            df = self._align_columns(df)

        # Step 3 — fill missing values
        if self.fill_missing:
            df = self._apply_fill_missing(df)

        # Step 4 — apply dtype casting
        if self.dtypes:
            df = self._apply_dtypes(df)

        log.info(
            "DataFrameBuilder: built DataFrame — {} rows × {} columns",
            len(df), len(df.columns)
        )

        return df

    def _align_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Ensures DataFrame has exactly the columns defined in self.columns,
        in that order. Missing columns are added as NaN. Extra columns dropped.

        This guarantees downstream code always gets the expected schema.
        """
        # Add any missing columns as NaN
        for col in self.columns:
            if col not in df.columns:
                df[col] = np.nan
                log.debug("DataFrameBuilder: added missing column '{}'", col)

        # Select only the defined columns in the defined order
        # This also drops any extra columns not in self.columns
        df = df[self.columns]

        return df

    def _apply_fill_missing(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Fills NaN values in specific columns with default values.

        Uses fillna() per column so only targeted columns are affected.
        """
        for col, default in self.fill_missing.items():
            if col in df.columns:
                df[col] = df[col].fillna(default)
        return df

    def _apply_dtypes(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Casts columns to specified dtypes.
        Failed casts are logged and the column is left as-is.

        Common dtype mappings:
            str   → object (pandas string type)
            float → float64
            int   → Int64 (nullable integer — handles NaN better than int64)
            bool  → bool
        """
        for col, dtype in self.dtypes.items():
            if col not in df.columns:
                continue
            try:
                if dtype == int:
                    # Use pandas nullable Int64 — handles NaN without crashing
                    df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
                elif dtype == float:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                elif dtype == bool:
                    df[col] = df[col].astype(bool)
                elif dtype == str:
                    # Replace NaN with empty string for string columns
                    df[col] = df[col].fillna("").astype(str)
                else:
                    df[col] = df[col].astype(dtype)

                log.debug("DataFrameBuilder: cast '{}' to {}", col, dtype.__name__)

            except Exception as e:
                log.warning(
                    "DataFrameBuilder: failed to cast '{}' to {}: {}",
                    col, dtype, str(e)
                )

        return df

    def build_empty(self) -> pd.DataFrame:
        """
        Returns an empty DataFrame with the correct schema.
        Useful when a scrape job returns no results — downstream code
        can still handle it without None checks.
        """
        cols = self.columns or []
        df = pd.DataFrame(columns=cols)
        if self.dtypes:
            df = self._apply_dtypes(df)
        return df

    @staticmethod
    def from_csv(filepath: str, **kwargs) -> pd.DataFrame:
        """
        Loads a DataFrame from a CSV file.
        A convenience wrapper around pd.read_csv with logging.

        Args:
            filepath: path to the CSV file
            **kwargs: passed directly to pd.read_csv

        Returns:
            loaded DataFrame
        """
        try:
            df = pd.read_csv(filepath, **kwargs)
            log.info("DataFrameBuilder: loaded {} rows from {}", len(df), filepath)
            return df
        except Exception as e:
            log.error("DataFrameBuilder: failed to load {}: {}", filepath, str(e))
            return pd.DataFrame()
