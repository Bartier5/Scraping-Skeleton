# ── examples/day13_example.py ─────────────────────────────────────────────────
# Day 13 mini example — JobScheduler and CLI demo.
#
# Run with: python examples/day13_example.py

import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from utils.logger import log
from utils.helpers import ensure_dir, timestamp
from scheduler.job_scheduler import JobScheduler


async def main():
    ensure_dir("logs")
    ensure_dir("data")

    log.info("=" * 60)
    log.info("Day 13 — Scheduler + CLI Demo")
    log.info("=" * 60)

    # ── 1. JobScheduler — run_once ────────────────────────────────────────────
    log.info("1. run_once — fire a job once after a delay:")

    scheduler = JobScheduler(timezone="UTC")
    await scheduler.start()

    results = {"counter": 0, "errors": 0}

    async def simple_job():
        results["counter"] += 1
        log.info("  [Job] simple_job fired — count={}", results["counter"])

    # Schedule to run immediately
    scheduler.run_once(simple_job, job_id="once_immediate", delay_seconds=0)

    # Schedule to run in 0.3 seconds
    scheduler.run_once(simple_job, job_id="once_delayed", delay_seconds=0)

    await asyncio.sleep(0.5)
    log.info("  Jobs fired: {}", results["counter"])
    log.info("  Job list: {}", [j["id"] for j in scheduler.get_jobs()])

    # ── 2. JobScheduler — run_interval ───────────────────────────────────────
    log.info("2. run_interval — fire every N seconds:")

    tick_count = {"n": 0}

    async def tick_job():
        tick_count["n"] += 1
        log.info("  [Tick] interval job fired — tick={}", tick_count["n"])

    # Run every 0.3 seconds — fast enough to see multiple fires in demo
    scheduler.run_interval(
        tick_job,
        job_id="fast_tick",
        seconds=0,          # APScheduler needs at least one non-zero field
        minutes=0,
        hours=0,
        # We'll use a workaround — run every 1 second for demo
    )

    # Actually use 1 second interval for visible demo
    scheduler.remove_job("fast_tick")
    scheduler.run_interval(
        tick_job,
        job_id="tick_1s",
        seconds=1,
        start_immediately=True,
    )

    log.info("  Waiting 3 seconds to observe interval job...")
    await asyncio.sleep(3.2)
    log.info("  Tick count after 3s: {} (expected ~3)", tick_count["n"])

    # ── 3. JobScheduler — pause and resume ────────────────────────────────────
    log.info("3. Pause and resume a job:")

    paused = scheduler.pause_job("tick_1s")
    log.info("  Paused tick_1s: {}", paused)
    tick_before = tick_count["n"]

    await asyncio.sleep(1.5)
    tick_after_pause = tick_count["n"]
    log.info("  Ticks while paused: {} (should be 0)", tick_after_pause - tick_before)

    resumed = scheduler.resume_job("tick_1s")
    log.info("  Resumed tick_1s: {}", resumed)

    await asyncio.sleep(1.5)
    tick_after_resume = tick_count["n"]
    log.info("  Ticks after resume: {} (should be ~1)", tick_after_resume - tick_after_pause)

    scheduler.remove_job("tick_1s")

    # ── 4. JobScheduler — error handling ─────────────────────────────────────
    log.info("4. Error handling — job that fails:")

    async def failing_job():
        log.warning("  [FailJob] raising exception...")
        raise ValueError("Simulated scrape failure")

    scheduler.run_once(failing_job, job_id="will_fail", delay_seconds=0)
    await asyncio.sleep(0.5)

    history = scheduler.get_job_history()
    errors = [h for h in history if h["status"] == "error"]
    log.info("  Error entries in history: {}", len(errors))
    if errors:
        log.info("  Error message: {}", errors[0].get("error"))

    # ── 5. Job history ────────────────────────────────────────────────────────
    log.info("5. Job execution history:")
    history = scheduler.get_job_history()
    log.info("  Total history entries: {}", len(history))
    for entry in history[-5:]:   # show last 5
        log.info("  {} → {} {}",
                 entry["job_id"],
                 entry["status"],
                 f"| {entry.get('error', '')}" if entry["status"] == "error" else "")

    # ── 6. JobScheduler — cron scheduling ────────────────────────────────────
    log.info("6. run_cron — calendar-based scheduling:")

    cron_fired = {"n": 0}

    async def daily_report():
        cron_fired["n"] += 1
        log.info("  [Cron] daily_report fired")

    # Schedule every day at 9am
    job = scheduler.run_cron(
        daily_report,
        job_id="daily_9am",
        hour="9",
        minute="0",
        day_of_week="*",
    )
    log.info("  Cron job '{}' registered", job.id)
    jobs = scheduler.get_jobs()
    cron_job = next((j for j in jobs if j["id"] == "daily_9am"), None)
    if cron_job:
        log.info("  Next run: {}", cron_job["next_run"])
        log.info("  Trigger: {}", cron_job["trigger"])

    # ── 7. JobScheduler summary ───────────────────────────────────────────────
    log.info("7. All registered jobs:")
    for job in scheduler.get_jobs():
        log.info("  {} | next: {}", job["id"], job["next_run"])

    log.info("  Scheduler: {}", scheduler)

    await scheduler.stop()
    log.info("  Scheduler stopped: is_running={}", scheduler.is_running)

    # ── 8. CLI usage examples ─────────────────────────────────────────────────
    log.info("8. CLI (main.py) usage:")
    log.info("  List spiders:")
    log.info("    python main.py --list-spiders")
    log.info("")
    log.info("  Single URL scrape:")
    log.info("    python main.py --spider example --mode single --url https://books.toscrape.com")
    log.info("")
    log.info("  Batch scrape with concurrency:")
    log.info("    python main.py --spider batch --mode batch --concurrency 10 --storage sqlite")
    log.info("")
    log.info("  Scheduled scrape every hour:")
    log.info("    python main.py --spider example --mode schedule --interval 3600")
    log.info("")
    log.info("  Cron scrape every day at 9am:")
    log.info("    python main.py --spider example --mode schedule --cron '0 9 * * *'")
    log.info("")
    log.info("  Dry run (validate config):")
    log.info("    python main.py --spider example --dry-run --url https://example.com")

    # ── 9. Dry run demo ───────────────────────────────────────────────────────
    log.info("9. Dry run demo:")

    from main import build_parser, main_async
    parser = build_parser()
    args = parser.parse_args([
        "--spider",      "example",
        "--mode",        "single",
        "--url",         "https://books.toscrape.com",
        "--storage",     "sqlite",
        "--concurrency", "5",
        "--dry-run",
    ])
    await main_async(args)

    log.info("=" * 60)
    log.success("Day 13 complete — scheduler and CLI working")
    log.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
