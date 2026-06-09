# ── pandas_layer/exporter.py ──────────────────────────────────────────────────
# DataFrame exporter — saves analyzed data to CSV, Excel, or JSON.
#
# What does the exporter do?
#   Takes a clean, analyzed DataFrame and writes it to disk in the
#   format the client needs. Handles path creation, timestamped filenames,
#   encoding, and logging automatically.
#
# Pipeline position:
#   Analyzer → [Exporter] → Storage (or directly to client)

import pandas as pd
from pathlib import Path
from typing import Optional
from utils.logger import log
from utils.helpers import ensure_dir, timestamp, get_output_path


class DataExporter:
    """
    Exports a Pandas DataFrame to CSV, Excel, or JSON.

    Usage:
        exporter = DataExporter(output_dir="data/exports")
        path = exporter.to_csv(df, filename="books")
        path = exporter.to_excel(df, filename="books")
        path = exporter.to_json(df, filename="books")
    """

    def __init__(self, output_dir: str = "data/"):
        """
        Args:
            output_dir: directory where exported files are saved
                        created automatically if it doesn't exist
        """
        self.output_dir = output_dir
        ensure_dir(output_dir)   # create directory if it doesn't exist
        log.debug("DataExporter initialized (output_dir={})", output_dir)

    def to_csv(
        self,
        df: pd.DataFrame,
        filename: str,
        include_timestamp: bool = True,
        encoding: str = "utf-8-sig",    # utf-8-sig adds BOM for Excel compatibility
        index: bool = False,            # don't write row numbers as a column
    ) -> str:
        """
        Exports DataFrame to a CSV file.

        Args:
            df:                DataFrame to export
            filename:          base filename without extension e.g. "books"
            include_timestamp: if True, appends timestamp to filename
                               "books" → "books_20250610_143022.csv"
            encoding:          file encoding. utf-8-sig recommended for Excel
                               compatibility — Excel opens it without garbling
            index:             if True, writes row index as first column

        Returns:
            full path of the written file
        """
        if df.empty:
            log.warning("DataExporter.to_csv: DataFrame is empty — skipping export")
            return ""

        fname = f"{filename}_{timestamp()}.csv" if include_timestamp else f"{filename}.csv"
        filepath = get_output_path(fname, self.output_dir)

        try:
            df.to_csv(
                filepath,
                index=index,
                encoding=encoding,
            )
            log.info(
                "DataExporter: exported {} rows to CSV → {}",
                len(df), filepath
            )
            return filepath

        except Exception as e:
            log.error("DataExporter.to_csv failed: {}", str(e))
            return ""

    def to_excel(
        self,
        df: pd.DataFrame,
        filename: str,
        sheet_name: str = "Data",
        include_timestamp: bool = True,
        index: bool = False,
    ) -> str:
        """
        Exports DataFrame to an Excel (.xlsx) file.
        Requires openpyxl to be installed (already in requirements).

        Args:
            df:                DataFrame to export
            filename:          base filename without extension
            sheet_name:        name of the Excel worksheet
            include_timestamp: if True, appends timestamp to filename
            index:             if True, writes row index as first column

        Returns:
            full path of the written file
        """
        if df.empty:
            log.warning("DataExporter.to_excel: DataFrame is empty — skipping export")
            return ""

        fname = f"{filename}_{timestamp()}.xlsx" if include_timestamp else f"{filename}.xlsx"
        filepath = get_output_path(fname, self.output_dir)

        try:
            # ExcelWriter gives more control than df.to_excel() directly
            # — can write multiple sheets, set column widths, etc.
            with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
                df.to_excel(
                    writer,
                    sheet_name=sheet_name,
                    index=index,
                )

                # Auto-adjust column widths to fit content
                # Makes the Excel file readable without manual resizing
                worksheet = writer.sheets[sheet_name]
                for col_num, col_name in enumerate(df.columns, 1):
                    # Get max length in the column (header or data)
                    max_len = max(
                        len(str(col_name)),
                        df[col_name].astype(str).str.len().max() if len(df) > 0 else 0
                    )
                    # Cap at 50 chars — very long columns make the file unwieldy
                    col_width = min(max_len + 2, 50)
                    # Excel column letters: A, B, C... 
                    col_letter = worksheet.cell(row=1, column=col_num).column_letter
                    worksheet.column_dimensions[col_letter].width = col_width

            log.info(
                "DataExporter: exported {} rows to Excel → {}",
                len(df), filepath
            )
            return filepath

        except Exception as e:
            log.error("DataExporter.to_excel failed: {}", str(e))
            return ""

    def to_json(
        self,
        df: pd.DataFrame,
        filename: str,
        orient: str = "records",        # "records" = list of dicts (most common)
        include_timestamp: bool = True,
        indent: int = 2,                # pretty-print with 2-space indent
    ) -> str:
        """
        Exports DataFrame to a JSON file.

        Args:
            df:                DataFrame to export
            filename:          base filename without extension
            orient:            JSON format. Options:
                               "records" → [{"col1": val, "col2": val}, ...]
                               "index"   → {"0": {"col1": val}, ...}
                               "columns" → {"col1": {"0": val}, ...}
                               "records" is the most useful for APIs and pipelines
            include_timestamp: if True, appends timestamp to filename
            indent:            JSON indentation spaces (0 = compact, 2 = readable)

        Returns:
            full path of the written file
        """
        if df.empty:
            log.warning("DataExporter.to_json: DataFrame is empty — skipping export")
            return ""

        fname = f"{filename}_{timestamp()}.json" if include_timestamp else f"{filename}.json"
        filepath = get_output_path(fname, self.output_dir)

        try:
            df.to_json(
                filepath,
                orient=orient,
                indent=indent,
                force_ascii=False,      # preserve non-ASCII chars (£, €, etc.)
                default_handler=str,    # convert any non-serializable values to str
            )
            log.info(
                "DataExporter: exported {} rows to JSON → {}",
                len(df), filepath
            )
            return filepath

        except Exception as e:
            log.error("DataExporter.to_json failed: {}", str(e))
            return ""

    def to_all(
        self,
        df: pd.DataFrame,
        filename: str,
        formats: list[str] = None,
    ) -> dict[str, str]:
        """
        Exports DataFrame to multiple formats in one call.

        Args:
            df:       DataFrame to export
            filename: base filename
            formats:  list of formats to export e.g. ["csv", "excel", "json"]
                      defaults to ["csv"] if not specified

        Returns:
            dict mapping format → filepath for each successful export
        """
        formats = formats or ["csv"]
        paths = {}

        for fmt in formats:
            if fmt == "csv":
                path = self.to_csv(df, filename)
            elif fmt in ("excel", "xlsx"):
                path = self.to_excel(df, filename)
            elif fmt == "json":
                path = self.to_json(df, filename)
            else:
                log.warning("DataExporter: unknown format '{}' — skipping", fmt)
                continue

            if path:
                paths[fmt] = path

        return paths

    @staticmethod
    def df_to_records(df: pd.DataFrame) -> list[dict]:
        """
        Converts a DataFrame back to a list of dicts.
        Used when passing data to the storage layer instead of a file.

        Handles NaN → None conversion so dicts are JSON-serializable.

        Returns:
            list of dicts with NaN replaced by None
        """
        # where(df.notna(), other=None) replaces NaN with None
        return df.where(df.notna(), other=None).to_dict(orient="records")
