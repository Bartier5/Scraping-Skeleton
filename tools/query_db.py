# ── tools/query_db.py ─────────────────────────────────────────────────────────
# Quick CLI tool to query any SQLite database produced by the scraper skeleton.
#
# Usage:
#   python tools/query_db.py --db data/quotes_js.db --table quotes
#   python tools/query_db.py --db data/quotes_js.db --table quotes --limit 5
#   python tools/query_db.py --db data/quotes_js.db --table quotes --where "author='Albert Einstein'"
#   python tools/query_db.py --db data/quotes_js.db --table quotes --export csv
#   python tools/query_db.py --db data/quotes_js.db --table quotes --count
#   python tools/query_db.py --db data/quotes_js.db --table quotes --authors

import sys
import os
import asyncio
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from storage.sqlite_storage import SqliteStorage
from utils.logger import log
from utils.helpers import ensure_dir


def build_parser():
    parser = argparse.ArgumentParser(
        prog="query_db",
        description="Query SQLite databases produced by scraper_skeleton",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python tools/query_db.py --db data/quotes_js.db --table quotes
  python tools/query_db.py --db data/quotes_js.db --table quotes --limit 5
  python tools/query_db.py --db data/quotes_js.db --table quotes --where "author='Albert Einstein'"
  python tools/query_db.py --db data/quotes_js.db --table quotes --export csv
  python tools/query_db.py --db data/quotes_js.db --table quotes --count
  python tools/query_db.py --db data/quotes_js.db --table quotes --authors
        """
    )
    parser.add_argument("--db",     required=True, help="Path to SQLite database file")
    parser.add_argument("--table",  required=True, help="Table name to query")
    parser.add_argument("--limit",  type=int, default=None, help="Max rows to return")
    parser.add_argument("--where",  type=str, default="",   help="SQL WHERE clause e.g. \"author='Einstein'\"")
    parser.add_argument("--export", type=str, choices=["csv", "excel", "json"], help="Export to file format")
    parser.add_argument("--count",  action="store_true", help="Show row count only")
    parser.add_argument("--schema", action="store_true", help="Show column names")
    parser.add_argument("--authors",action="store_true", help="List unique authors (quotes DB only)")
    return parser


async def main():
    parser = build_parser()
    args = parser.parse_args()

    if not os.path.exists(args.db):
        print(f"Error: database not found — {args.db}")
        sys.exit(1)

    storage = SqliteStorage(db_path=args.db, table_name=args.table)

    # ── Count only ────────────────────────────────────────────────────────────
    if args.count:
        count = await storage.count()
        print(f"\n  Table '{args.table}': {count} rows\n")
        return

    # ── Load rows ─────────────────────────────────────────────────────────────
    rows = await storage.load(limit=args.limit, where=args.where)

    if not rows:
        print(f"\n  No rows found in '{args.table}'" +
              (f" matching WHERE {args.where}" if args.where else "") + "\n")
        return

    # ── Schema ────────────────────────────────────────────────────────────────
    if args.schema:
        print(f"\n  Columns in '{args.table}':")
        for col in rows[0].keys():
            print(f"    {col}")
        print()
        return

    # ── Unique authors ────────────────────────────────────────────────────────
    if args.authors:
        all_rows = await storage.load()
        authors = sorted(set(r.get("author", "") for r in all_rows if r.get("author")))
        print(f"\n  Unique authors ({len(authors)}):")
        for a in authors:
            count = sum(1 for r in all_rows if r.get("author") == a)
            print(f"    {a} ({count} quotes)")
        print()
        return

    # ── Export ────────────────────────────────────────────────────────────────
    if args.export:
        import pandas as pd
        from pandas_layer.exporter import DataExporter

        ensure_dir("data/exports")
        df = pd.DataFrame(rows)
        exporter = DataExporter(output_dir="data/exports")

        table_name = args.table

        if args.export == "csv":
            path = exporter.to_csv(df, table_name, include_timestamp=True)
            print(f"\n  Exported {len(df)} rows to CSV → {path}\n")
        elif args.export == "excel":
            path = exporter.to_excel(df, table_name, include_timestamp=True)
            print(f"\n  Exported {len(df)} rows to Excel → {path}\n")
        elif args.export == "json":
            path = exporter.to_json(df, table_name, include_timestamp=True)
            print(f"\n  Exported {len(df)} rows to JSON → {path}\n")
        return

    # ── Print rows ────────────────────────────────────────────────────────────
    total = await storage.count()
    showing = len(rows)

    print(f"\n  Table: '{args.table}' | Total rows: {total} | Showing: {showing}")
    if args.where:
        print(f"  Filter: WHERE {args.where}")
    print(f"  {'─' * 70}")

    for i, row in enumerate(rows, 1):
        # Detect what kind of data this is and format accordingly
        if "text" in row and "author" in row:
            # Quotes format
            text = str(row.get("text", ""))[:65]
            author = row.get("author", "Unknown")
            tags = row.get("tags", "")
            print(f"  {i:>3}. {text}...")
            print(f"       — {author}")
            if tags:
                print(f"       Tags: {str(tags)[:60]}")
            print()
        elif "title" in row and "price" in row:
            # Books format
            title = str(row.get("title", ""))[:40]
            price = row.get("price", "N/A")
            avail = str(row.get("availability", "")).strip()
            print(f"  {i:>3}. {title}")
            print(f"       Price: £{price} | {avail}")
            print()
        else:
            # Generic format — print all fields
            print(f"  {i:>3}. Row {i}")
            for k, v in row.items():
                if k not in ("id", "inserted_at") and v:
                    print(f"       {k}: {str(v)[:60]}")
            print()

    print(f"  {'─' * 70}")
    print(f"  {showing} row(s) shown\n")


if __name__ == "__main__":
    asyncio.run(main())