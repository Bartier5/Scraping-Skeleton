# ── main.py ───────────────────────────────────────────────────────────────────
# CLI entry point for the scraper skeleton.
#
# Provides a unified command-line interface for running any spider
# with configurable fetcher, storage backend, concurrency, and scheduling.
#
# Usage examples:
#   python main.py --spider example --mode single --url https://books.toscrape.com
#   python main.py --spider batch   --mode batch  --concurrency 10 --storage sqlite
#   python main.py --spider example --mode schedule --interval 3600
#   python main.py --list-spiders
#
# Run with --help for full usage:
#   python main.py --help

import asyncio
import sys
import os
import argparse
from datetime import datetime, timezone

# Add project root to path so all imports resolve
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from utils.logger import log
from utils.helpers import ensure_dir, timestamp
from config.config import Config


# ── Spider registry ───────────────────────────────────────────────────────────
# Maps spider names to their module paths and descriptions.
# Add new spiders here as you build them in the spiders/ folder.

SPIDER_REGISTRY = {
    "example": {
        "module": "spiders.example_spider",
        "class":  "ExampleSpider",
        "description": "Single-URL scraper — books.toscrape.com demo",
    },
    "batch": {
        "module": "spiders.batch_spider",
        "class":  "BatchSpider",
        "description": "Batch URL scraper — multiple pages concurrently",
    },
    "quotes_js": {
    "module": "spiders.quotes_js_spider",
    "class":  "QuotesJsSpider",
    "description": "JS-rendered quotes — Playwright demo",
},
    "infinite_scroll": {
    "module": "spiders.infinite_scroll_spider",
    "class":  "InfiniteScrollSpider",
    "description": "Infinite scroll — quotes.toscrape.com/scroll demo",
},
}


def build_parser() -> argparse.ArgumentParser:
    """
    Builds the argument parser for the CLI.
    Returns an ArgumentParser with all supported flags.
    """
    parser = argparse.ArgumentParser(
        prog="scraper_skeleton",
        description="Production-grade Python scraper skeleton",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --spider example --mode single --url https://books.toscrape.com
  python main.py --spider batch --mode batch --concurrency 10 --storage sqlite
  python main.py --spider example --mode schedule --interval 3600
  python main.py --list-spiders
        """
    )

    # ── Spider selection ──────────────────────────────────────────────────────
    parser.add_argument(
        "--spider",
        type=str,
        default="example",
        help="Spider to run (default: example). Use --list-spiders to see all."
    )

    parser.add_argument(
        "--list-spiders",
        action="store_true",
        help="List all available spiders and exit"
    )

    # ── Run mode ──────────────────────────────────────────────────────────────
    parser.add_argument(
        "--mode",
        type=str,
        choices=["single", "batch", "schedule"],
        default="single",
        help=(
            "Run mode: "
            "'single' = fetch one URL, "
            "'batch' = fetch multiple URLs concurrently, "
            "'schedule' = run on a schedule"
        )
    )

    # ── URL / input ───────────────────────────────────────────────────────────
    parser.add_argument(
        "--url",
        type=str,
        default="",
        help="Target URL (single mode)"
    )

    parser.add_argument(
        "--urls-file",
        type=str,
        default="",
        help="Path to a text file with one URL per line (batch mode)"
    )

    # ── Fetcher config ────────────────────────────────────────────────────────
    parser.add_argument(
        "--fetcher",
        type=str,
        choices=["http", "async", "batch", "browser"],
        default="async",
        help="Fetcher to use (default: async)"
    )

    parser.add_argument(
        "--concurrency",
        type=int,
        default=Config.CONCURRENCY,
        help=f"Max concurrent requests (default: {Config.CONCURRENCY})"
    )

    # ── Storage config ────────────────────────────────────────────────────────
    parser.add_argument(
        "--storage",
        type=str,
        choices=["csv", "sqlite", "postgres"],
        default=Config.STORAGE_BACKEND,
        help=f"Storage backend (default: {Config.STORAGE_BACKEND})"
    )

    parser.add_argument(
        "--output",
        type=str,
        default=Config.OUTPUT_DIR,
        help=f"Output directory for CSV/files (default: {Config.OUTPUT_DIR})"
    )

    # ── Schedule config ───────────────────────────────────────────────────────
    parser.add_argument(
        "--interval",
        type=int,
        default=0,
        help="Schedule interval in seconds (schedule mode)"
    )

    parser.add_argument(
        "--cron",
        type=str,
        default="",
        help=(
            "Cron expression for schedule mode "
            "e.g. '0 9 * * *' = every day at 9am"
        )
    )

    # ── Anti-bot config ───────────────────────────────────────────────────────
    parser.add_argument(
        "--proxies-file",
        type=str,
        default=Config.PROXY_LIST,
        help="Path to proxy list file (one proxy per line)"
    )

    parser.add_argument(
        "--no-rotate-headers",
        action="store_true",
        help="Disable header rotation (use fixed headers)"
    )

    # ── Misc ──────────────────────────────────────────────────────────────────
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate config and show what would run, without actually running"
    )

    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default=Config.LOG_LEVEL,
        help=f"Logging level (default: {Config.LOG_LEVEL})"
    )

    return parser


def list_spiders() -> None:
    """Prints all registered spiders in a formatted table."""
    print("\nAvailable spiders:")
    print("-" * 60)
    for name, info in SPIDER_REGISTRY.items():
        print(f"  {name:<15} {info['description']}")
    print("-" * 60)
    print(f"  Total: {len(SPIDER_REGISTRY)} spider(s)")
    print()


def load_spider(spider_name: str):
    """
    Dynamically imports and returns the spider class by name.
    Raises SystemExit if the spider is not found.

    Args:
        spider_name: key in SPIDER_REGISTRY

    Returns:
        Spider class (not instance)
    """
    if spider_name not in SPIDER_REGISTRY:
        log.error(
            "Spider '{}' not found. Use --list-spiders to see available spiders.",
            spider_name
        )
        sys.exit(1)

    info = SPIDER_REGISTRY[spider_name]
    try:
        import importlib
        module = importlib.import_module(info["module"])
        spider_class = getattr(module, info["class"])
        log.debug("Loaded spider: {} from {}", info["class"], info["module"])
        return spider_class
    except (ImportError, AttributeError) as e:
        log.error("Failed to load spider '{}': {}", spider_name, str(e))
        sys.exit(1)


def build_storage(storage_type: str, output_dir: str):
    """
    Instantiates the appropriate storage backend based on CLI args.

    Args:
        storage_type: "csv", "sqlite", or "postgres"
        output_dir:   output directory for CSV files

    Returns:
        Storage instance
    """
    ensure_dir(output_dir)

    if storage_type == "csv":
        from storage.csv_storage import CsvStorage
        filepath = os.path.join(output_dir, f"output_{timestamp()}.csv")
        return CsvStorage(filepath=filepath, mode="append")

    elif storage_type == "sqlite":
        from storage.sqlite_storage import SqliteStorage
        db_path = os.path.join(output_dir, "scraper.db")
        return SqliteStorage(db_path=db_path)

    elif storage_type == "postgres":
        from storage.postgres_storage import PostgresStorage
        if not Config.POSTGRES_URL:
            log.error(
                "POSTGRES_URL not set in .env — cannot use postgres storage. "
                "Set POSTGRES_URL or use --storage sqlite"
            )
            sys.exit(1)
        return PostgresStorage(dsn=Config.POSTGRES_URL)

    else:
        log.error("Unknown storage type: {}", storage_type)
        sys.exit(1)


async def run_single(args, spider_class, storage) -> None:
    """Runs a spider once against a single URL."""
    if not args.url:
        log.error("--url is required for single mode")
        sys.exit(1)

    log.info("Running spider '{}' in single mode against: {}", args.spider, args.url)
    spider = spider_class(storage=storage, concurrency=args.concurrency)
    await spider.run(urls=[args.url])


async def run_batch(args, spider_class, storage) -> None:
    """Runs a spider against multiple URLs from a file or config."""
    urls = []

    if args.urls_file:
        if not os.path.exists(args.urls_file):
            log.error("URLs file not found: {}", args.urls_file)
            sys.exit(1)
        with open(args.urls_file) as f:
            urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]
        log.info("Loaded {} URLs from {}", len(urls), args.urls_file)
    elif args.url:
        urls = [args.url]
    else:
        log.error("--url or --urls-file required for batch mode")
        sys.exit(1)

    log.info(
        "Running spider '{}' in batch mode — {} URLs (concurrency={})",
        args.spider, len(urls), args.concurrency
    )
    spider = spider_class(storage=storage, concurrency=args.concurrency)
    await spider.run(urls=urls)


async def run_scheduled(args, spider_class, storage) -> None:
    """Runs a spider on a schedule using JobScheduler."""
    from scheduler.job_scheduler import JobScheduler

    if not args.interval and not args.cron:
        log.error("--interval or --cron required for schedule mode")
        sys.exit(1)

    scheduler = JobScheduler(timezone="UTC")
    await scheduler.start()

    # Define the job function
    async def scrape_job():
        log.info("Scheduled job starting: '{}'", args.spider)
        spider = spider_class(storage=storage, concurrency=args.concurrency)
        url = args.url or "https://books.toscrape.com/catalogue/page-1.html"
        await spider.run(urls=[url])
        log.info("Scheduled job complete: '{}'", args.spider)

    # Add the job
    if args.interval:
        scheduler.run_interval(
            scrape_job,
            job_id=f"{args.spider}_interval",
            seconds=args.interval,
            start_immediately=True,
        )
        log.info("Scheduled to run every {}s", args.interval)

    elif args.cron:
        # Parse cron string "sec min hour day month dow"
        parts = args.cron.split()
        if len(parts) == 5:
            # Standard 5-part cron: min hour day month dow
            minute, hour, day, month, dow = parts
            scheduler.run_cron(
                scrape_job,
                job_id=f"{args.spider}_cron",
                minute=minute, hour=hour,
                day=day, month=month, day_of_week=dow,
            )
        else:
            log.error("Invalid cron expression: '{}' — use 5 parts: min hour day month dow", args.cron)
            sys.exit(1)

    log.info("Scheduler running — press Ctrl+C to stop")
    await scheduler.wait()


async def main_async(args) -> None:
    """Main async entry point — dispatches to the appropriate run mode."""
    ensure_dir("logs")
    ensure_dir("data")

    if args.dry_run:
        log.info("DRY RUN — configuration summary:")
        log.info("  Spider:      {}", args.spider)
        log.info("  Mode:        {}", args.mode)
        log.info("  Fetcher:     {}", args.fetcher)
        log.info("  Concurrency: {}", args.concurrency)
        log.info("  Storage:     {}", args.storage)
        log.info("  Output:      {}", args.output)
        if args.url:
            log.info("  URL:         {}", args.url)
        if args.interval:
            log.info("  Interval:    {}s", args.interval)
        if args.cron:
            log.info("  Cron:        {}", args.cron)
        log.info("Dry run complete — no requests made")
        return

    # Load spider and storage
    spider_class = load_spider(args.spider)
    storage = build_storage(args.storage, args.output)

    log.info("=" * 50)
    log.info("Scraper Skeleton")
    log.info("  Spider:  {} | Mode: {} | Storage: {}",
             args.spider, args.mode, args.storage)
    log.info("=" * 50)

    start_time = datetime.now(timezone.utc)

    try:
        if args.mode == "single":
            await run_single(args, spider_class, storage)
        elif args.mode == "batch":
            await run_batch(args, spider_class, storage)
        elif args.mode == "schedule":
            await run_scheduled(args, spider_class, storage)

    except KeyboardInterrupt:
        log.info("Interrupted by user")
    except Exception as e:
        log.error("Fatal error: {}", str(e))
        raise

    elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
    log.info("Finished in {:.2f}s", elapsed)


def main() -> None:
    """Synchronous entry point — parses args and runs the async main."""
    parser = build_parser()
    args = parser.parse_args()

    if args.list_spiders:
        list_spiders()
        sys.exit(0)

    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
