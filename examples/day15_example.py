# ── examples/day15_example.py ─────────────────────────────────────────────────
# Day 15 — Final system check.
# Runs a quick smoke test across all layers to confirm the full skeleton
# is wired correctly before the final commit and tag.
#
# Run with: python examples/day15_example.py

import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from utils.logger import log
from utils.helpers import ensure_dir, hash_content, timestamp


async def main():
    ensure_dir("logs")
    ensure_dir("data")

    log.info("=" * 60)
    log.info("Day 15 — Final System Check")
    log.info("=" * 60)

    results = {}

    # ── 1. Import check — all layers ──────────────────────────────────────────
    log.info("1. Import check — all layers:")

    layers = {
        "config":         "from config.config import Config",
        "logger":         "from utils.logger import log",
        "helpers":        "from utils.helpers import ensure_dir, hash_content",
        "rate_limiter":   "from utils.rate_limiter import RateLimiter",
        "url_utils":      "from utils.url_utils import prepare_urls",
        "http_fetcher":   "from fetcher.http_fetcher import HttpFetcher",
        "async_fetcher":  "from fetcher.async_fetcher import AsyncFetcher",
        "batch_fetcher":  "from fetcher.batch_fetcher import BatchFetcher",
        "bs4_parser":     "from parser.bs4_parser import BS4Parser",
        "lxml_parser":    "from parser.lxml_parser import LxmlParser",
        "middleware":     "from middleware.base_middleware import MiddlewareChain",
        "cleaner":        "from pipeline.cleaner import DataCleaner",
        "transformer":    "from pipeline.transformer import DataTransformer",
        "validator":      "from pipeline.validator import DataValidator",
        "df_builder":     "from pandas_layer.dataframe_builder import DataFrameBuilder",
        "analyzer":       "from pandas_layer.analyzer import DataAnalyzer",
        "exporter":       "from pandas_layer.exporter import DataExporter",
        "csv_storage":    "from storage.csv_storage import CsvStorage",
        "sqlite_storage": "from storage.sqlite_storage import SqliteStorage",
        "checkpoint_mgr": "from storage.checkpoint_manager import CheckpointManager",
        "postgres_storage":"from storage.postgres_storage import PostgresStorage",
        "proxy_manager":  "from anti_bot.proxy_manager import ProxyManager",
        "headers_manager":"from anti_bot.headers_manager import HeadersManager",
        "fingerprint_mgr":"from anti_bot.fingerprint_manager import FingerprintAnalyzer",
        "scheduler":      "from scheduler.job_scheduler import JobScheduler",
        "base_spider":    "from spiders.base_spider import BaseSpider",
        "example_spider": "from spiders.example_spider import ExampleSpider",
        "batch_spider":   "from spiders.batch_spider import BatchSpider",
        "main_cli":       "from main import build_parser, SPIDER_REGISTRY",
    }

    passed = 0
    failed = []
    for name, import_stmt in layers.items():
        try:
            exec(import_stmt)
            passed += 1
            log.debug("  ✓ {}", name)
        except Exception as e:
            failed.append((name, str(e)))
            log.error("  ✗ {} — {}", name, str(e))

    log.info("  Import check: {}/{} layers OK", passed, len(layers))
    results["imports"] = {"passed": passed, "failed": len(failed), "total": len(layers)}

    if failed:
        log.warning("  Failed imports:")
        for name, err in failed:
            log.warning("    {} — {}", name, err)

    # ── 2. Pipeline smoke test ────────────────────────────────────────────────
    log.info("2. Pipeline smoke test — HTML → parser → pipeline → storage:")

    HTML = """<html><body>
    <article class="product_pod">
      <h3><a href="../book-a_1/index.html">Book A</a></h3>
      <p class="price_color">£9.99</p>
      <p class="star-rating Three"></p>
      <p class="availability">In stock</p>
    </article>
    <article class="product_pod">
      <h3><a href="../book-b_2/index.html">Book B</a></h3>
      <p class="price_color">£14.99</p>
      <p class="star-rating Five"></p>
      <p class="availability">In stock</p>
    </article>
    </html>"""

    from parser.bs4_parser import BS4Parser
    from pipeline.cleaner import DataCleaner
    from pipeline.transformer import DataTransformer
    from pipeline.validator import DataValidator, BookSchema
    from storage.sqlite_storage import SqliteStorage

    parser = BS4Parser()
    soup = parser.make_soup(HTML)

    titles  = parser.get_all_text(soup, "h3 > a")
    prices  = parser.get_all_text(soup, "p.price_color")
    ratings = parser.get_all_attr(soup, "p.star-rating", "class")
    avails  = parser.get_all_text(soup, "p.availability")
    links   = parser.get_all_attr(soup, "h3 > a", "href")

    raw_items = [
        {
            "title":        t,
            "price_raw":    p,
            "rating":       " ".join(r) if isinstance(r, list) else r,
            "availability": a,
            "url": f"https://books.toscrape.com/catalogue/{l.replace('../', '')}",
        }
        for t, p, r, a, l in zip(titles, prices, ratings, avails, links)
    ]

    cleaner     = DataCleaner()
    transformer = DataTransformer(
        computed={"price": lambda item: DataCleaner.extract_number(
            item.get("price_raw", "") or "")},
        add_metadata=True,
    )
    validator   = DataValidator(schema=BookSchema, strict=False)

    cleaned     = cleaner.clean_items(raw_items)
    transformed = transformer.transform_items(cleaned)
    batch       = validator.validate_batch(transformed)

    storage = SqliteStorage(db_path="data/day15_smoke.db")
    await storage.clear()
    save_result = await storage.save(batch.valid_items)
    count = await storage.count()

    pipeline_ok = (
        len(raw_items) == 2 and
        batch.pass_rate == 1.0 and
        save_result.success and
        count == 2
    )

    log.info("  Raw items:    {}", len(raw_items))
    log.info("  Valid items:  {}", len(batch.valid_items))
    log.info("  Pass rate:    {:.0%}", batch.pass_rate)
    log.info("  Saved to DB:  {}", save_result.rows_saved)
    log.info("  DB count:     {}", count)
    log.info("  Pipeline OK:  {}", pipeline_ok)
    results["pipeline"] = pipeline_ok

    # ── 3. Checkpoint smoke test ───────────────────────────────────────────────
    log.info("3. Checkpoint smoke test:")

    from storage.checkpoint_manager import CheckpointManager
    cp = CheckpointManager(db_path="data/day15_cp_smoke.db")
    await cp.init()
    await cp.reset()

    test_urls = [f"https://example.com/page-{i}" for i in range(1, 6)]

    for url in test_urls[:3]:
        await cp.mark_done(url, content_hash=hash_content(f"content-{url}"))

    pending = await cp.get_pending(test_urls)
    stats = await cp.get_stats()

    cp_ok = (
        len(pending) == 2 and
        stats["done"] == 3 and
        stats["total_seen"] == 3
    )

    log.info("  Done: {} | Pending: {} | Total seen: {}",
             stats["done"], len(pending), stats["total_seen"])
    log.info("  Checkpoint OK: {}", cp_ok)
    results["checkpoint"] = cp_ok

    # ── 4. Anti-bot smoke test ─────────────────────────────────────────────────
    log.info("4. Anti-bot smoke test:")

    from anti_bot.proxy_manager import ProxyManager
    from anti_bot.headers_manager import HeadersManager
    from anti_bot.fingerprint_manager import FingerprintAnalyzer

    pm = ProxyManager()
    pm.load_from_list(["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"])

    hm = HeadersManager(browser="chrome", use_fake_ua=False)
    headers = hm.get_headers(url="https://example.com")

    fa = FingerprintAnalyzer()
    report = fa.check_headers(headers)

    antibot_ok = (
        len(pm) == 2 and
        "User-Agent" in headers and
        report["risk_score"] <= 3
    )

    log.info("  Proxy pool:    {} proxies", len(pm))
    log.info("  Header count:  {}", len(headers))
    log.info("  Risk score:    {} ({})", report["risk_score"], report["risk_level"])
    log.info("  Anti-bot OK:   {}", antibot_ok)
    results["anti_bot"] = antibot_ok

    # ── 5. Scheduler smoke test ────────────────────────────────────────────────
    log.info("5. Scheduler smoke test:")

    from scheduler.job_scheduler import JobScheduler

    scheduler = JobScheduler(timezone="UTC")
    await scheduler.start()

    fired = {"n": 0}

    async def test_job():
        fired["n"] += 1

    scheduler.run_once(test_job, job_id="smoke_once", delay_seconds=0)
    await asyncio.sleep(0.3)
    await scheduler.stop()

    scheduler_ok = fired["n"] == 1
    log.info("  Job fired: {} time(s)", fired["n"])
    log.info("  Scheduler OK: {}", scheduler_ok)
    results["scheduler"] = scheduler_ok

    # ── 6. CLI smoke test ─────────────────────────────────────────────────────
    log.info("6. CLI smoke test:")

    from main import build_parser, main_async, SPIDER_REGISTRY
    parser_cli = build_parser()
    args = parser_cli.parse_args([
        "--spider", "example",
        "--mode", "single",
        "--url", "https://books.toscrape.com",
        "--storage", "sqlite",
        "--dry-run",
    ])
    await main_async(args)

    cli_ok = (
        "example" in SPIDER_REGISTRY and
        "batch" in SPIDER_REGISTRY
    )
    log.info("  Spiders registered: {}", list(SPIDER_REGISTRY.keys()))
    log.info("  CLI OK: {}", cli_ok)
    results["cli"] = cli_ok

    # ── Final report ──────────────────────────────────────────────────────────
    log.info("=" * 60)
    log.info("FINAL SYSTEM CHECK REPORT")
    log.info("=" * 60)

    all_ok = True
    checks = [
        ("Import check",      results["imports"]["passed"] == results["imports"]["total"]),
        ("Pipeline e2e",      results["pipeline"]),
        ("Checkpointing",     results["checkpoint"]),
        ("Anti-bot stack",    results["anti_bot"]),
        ("Scheduler",         results["scheduler"]),
        ("CLI",               results["cli"]),
    ]

    for label, ok in checks:
        status = "✓ PASS" if ok else "✗ FAIL"
        log.info("  {} — {}", status, label)
        if not ok:
            all_ok = False

    log.info("=" * 60)
    if all_ok:
        log.success("ALL CHECKS PASSED — skeleton is production ready")
        log.info("")
        log.info("Next steps:")
        log.info("  git add .")
        log.info("  git commit -m 'day-15: tests, README, final polish — skeleton complete'")
        log.info("  git push origin dev")
        log.info("  git checkout main && git merge dev")
        log.info("  git tag v1.0.0 && git push origin v1.0.0")
    else:
        log.error("SOME CHECKS FAILED — review errors above before tagging")

    log.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
