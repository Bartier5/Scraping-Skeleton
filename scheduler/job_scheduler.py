# ── scheduler/job_scheduler.py ────────────────────────────────────────────────
# APScheduler wrapper for running scrape jobs on a schedule.
#
# What does the scheduler do?
#   Instead of running a spider manually every time, the scheduler runs it
#   automatically on a cron, interval, or one-off basis. This is what
#   turns a one-time scrape into a recurring data pipeline.
#
# Three job types:
#   - run_once:     fire at a specific datetime or after a delay
#   - run_interval: fire every N seconds/minutes/hours (price monitor, news feed)
#   - run_cron:     fire on a cron expression (every day at 9am, every Monday, etc.)
#
# Built on APScheduler 3.x with AsyncIOScheduler for full async support.
# Jobs survive restart if using SQLite job store (persistent mode).

import asyncio
from datetime import datetime, timezone, timedelta
from typing import Callable, Optional, Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.job import Job
from apscheduler.events import (
    EVENT_JOB_EXECUTED,     # fires after a job completes successfully
    EVENT_JOB_ERROR,        # fires when a job raises an exception
    EVENT_JOB_MISSED,       # fires when a job was skipped (took too long)
)

from utils.logger import log
from config.config import Config


class JobScheduler:
    """
    APScheduler wrapper for scrape job scheduling.

    Provides a clean interface over APScheduler's AsyncIOScheduler
    with logging, error handling, and job management built in.

    Usage:
        scheduler = JobScheduler()
        await scheduler.start()

        # Run every hour
        scheduler.run_interval(my_spider, hours=1, job_id="price_monitor")

        # Run every day at 9am
        scheduler.run_cron(my_spider, hour=9, minute=0, job_id="daily_scrape")

        # Run once in 5 minutes
        scheduler.run_once(my_spider, delay_seconds=300, job_id="one_off")

        # Keep running until stopped
        await scheduler.wait()

        await scheduler.stop()
    """

    def __init__(
        self,
        persistent: bool = False,      # if True, jobs survive restart (SQLite store)
        db_path: str = "data/scheduler.db",
        timezone: str = "UTC",
        max_instances: int = 1,        # max concurrent instances of the same job
    ):
        """
        Args:
            persistent:    if True, use SQLite job store — jobs survive restart
                           if False (default), use in-memory store
            db_path:       path for the SQLite job store (persistent mode only)
            timezone:      scheduler timezone e.g. "UTC", "Africa/Lagos"
            max_instances: max concurrent instances of any single job
                           1 = only one instance of each job at a time
        """
        self.timezone = timezone
        self.max_instances = max_instances
        self._running = False
        self._job_history: list[dict] = []   # track execution history

        # Configure job store
        if persistent:
            try:
                from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
                from utils.helpers import ensure_dir
                from pathlib import Path
                ensure_dir(str(Path(db_path).parent))
                jobstores = {
                    "default": SQLAlchemyJobStore(url=f"sqlite:///{db_path}")
                }
                log.debug("JobScheduler: using SQLite job store ({})", db_path)
            except ImportError:
                log.warning(
                    "SQLAlchemyJobStore not available — falling back to memory store. "
                    "Install sqlalchemy for persistent scheduling."
                )
                jobstores = {"default": MemoryJobStore()}
        else:
            jobstores = {"default": MemoryJobStore()}

        # Configure executor — AsyncIOExecutor runs async jobs natively
        executors = {
            "default": AsyncIOExecutor(),
        }

        # Job defaults — applied to all jobs unless overridden
        job_defaults = {
            "max_instances": max_instances,
            "coalesce": True,   # if multiple instances missed, only run once to catch up
        }

        self._scheduler = AsyncIOScheduler(
            jobstores=jobstores,
            executors=executors,
            job_defaults=job_defaults,
            timezone=timezone,
        )

        # Register event listeners for logging
        self._scheduler.add_listener(self._on_job_executed, EVENT_JOB_EXECUTED)
        self._scheduler.add_listener(self._on_job_error, EVENT_JOB_ERROR)
        self._scheduler.add_listener(self._on_job_missed, EVENT_JOB_MISSED)

        log.debug(
            "JobScheduler initialized (persistent={}, timezone={}, max_instances={})",
            persistent, timezone, max_instances
        )

    async def start(self) -> None:
        """
        Starts the scheduler. Must be called before adding jobs.
        The scheduler runs in the background — your code continues executing.
        """
        if not self._running:
            self._scheduler.start()
            self._running = True
            log.info("JobScheduler: started")

    async def stop(self, wait: bool = True) -> None:
        """
        Stops the scheduler.

        Args:
            wait: if True, waits for running jobs to complete before stopping
                  if False, stops immediately (running jobs are interrupted)
        """
        if self._running:
            self._scheduler.shutdown(wait=wait)
            self._running = False
            log.info("JobScheduler: stopped")

    def run_once(
        self,
        func: Callable,
        job_id: str,
        delay_seconds: int = 0,
        run_at: Optional[datetime] = None,
        args: tuple = (),
        kwargs: dict = None,
    ) -> Job:
        """
        Schedules a job to run once — either immediately, after a delay,
        or at a specific datetime.

        Args:
            func:           the async or sync function to run
            job_id:         unique identifier for this job
            delay_seconds:  run after this many seconds from now (0 = now)
            run_at:         run at this specific datetime (overrides delay_seconds)
            args:           positional arguments to pass to func
            kwargs:         keyword arguments to pass to func

        Returns:
            APScheduler Job object
        """
        if run_at:
            trigger_time = run_at
        else:
            trigger_time = datetime.now(tz=timezone.utc) + timedelta(seconds=delay_seconds)

        job = self._scheduler.add_job(
            func,
            trigger="date",             # "date" trigger fires once at a specific time
            run_date=trigger_time,
            id=job_id,
            args=args,
            kwargs=kwargs or {},
            replace_existing=True,      # replace if job with same ID exists
        )

        log.info(
            "JobScheduler: '{}' scheduled to run once at {}",
            job_id, trigger_time.strftime("%Y-%m-%d %H:%M:%S UTC")
        )
        return job

    def run_interval(
        self,
        func: Callable,
        job_id: str,
        seconds: int = 0,
        minutes: int = 0,
        hours: int = 0,
        days: int = 0,
        start_immediately: bool = True,
        args: tuple = (),
        kwargs: dict = None,
    ) -> Job:
        """
        Schedules a job to run repeatedly at a fixed interval.

        Use for: price monitors, live score trackers, news feeds,
                 anything that needs to check for updates regularly.

        Args:
            func:             function to run
            job_id:           unique identifier
            seconds/minutes/hours/days: interval duration (combined)
            start_immediately: if True, runs once immediately when added
                               if False, waits for first interval to elapse
            args/kwargs:      passed to func

        Returns:
            APScheduler Job object

        Example:
            # Run every 30 minutes
            scheduler.run_interval(scrape_prices, "prices", minutes=30)

            # Run every 2 hours
            scheduler.run_interval(scrape_jobs, "jobs", hours=2)
        """
        start_date = datetime.now(tz=timezone.utc) if start_immediately else None

        job = self._scheduler.add_job(
            func,
            trigger="interval",         # "interval" trigger fires repeatedly
            seconds=seconds,
            minutes=minutes,
            hours=hours,
            days=days,
            id=job_id,
            start_date=start_date,
            args=args,
            kwargs=kwargs or {},
            replace_existing=True,
        )

        # Build human-readable interval description for logging
        parts = []
        if days:    parts.append(f"{days}d")
        if hours:   parts.append(f"{hours}h")
        if minutes: parts.append(f"{minutes}m")
        if seconds: parts.append(f"{seconds}s")
        interval_str = " ".join(parts) or "0s"

        log.info(
            "JobScheduler: '{}' scheduled to run every {}",
            job_id, interval_str
        )
        return job

    def run_cron(
        self,
        func: Callable,
        job_id: str,
        second: str = "0",
        minute: str = "0",
        hour: str = "0",
        day: str = "*",
        month: str = "*",
        day_of_week: str = "*",
        args: tuple = (),
        kwargs: dict = None,
    ) -> Job:
        """
        Schedules a job using a cron-style schedule.

        Use for: daily reports, weekly exports, monthly summaries,
                 anything with a calendar-based schedule.

        Cron field syntax:
            "*"     = every value
            "0"     = at value 0
            "0,12"  = at 0 and 12
            "*/6"   = every 6 units
            "9-17"  = from 9 to 17

        Args:
            func:         function to run
            job_id:       unique identifier
            second:       seconds field (0-59)
            minute:       minutes field (0-59)
            hour:         hours field (0-23)
            day:          day of month (1-31)
            month:        month (1-12)
            day_of_week:  day of week (0-6 or mon,tue,wed,thu,fri,sat,sun)
            args/kwargs:  passed to func

        Returns:
            APScheduler Job object

        Examples:
            # Every day at 9am UTC
            scheduler.run_cron(scrape, "daily", hour="9", minute="0")

            # Every Monday at 8am
            scheduler.run_cron(scrape, "weekly", hour="8", day_of_week="mon")

            # Every hour on the half hour
            scheduler.run_cron(scrape, "half_hourly", minute="30")

            # Every weekday at 9am and 5pm
            scheduler.run_cron(scrape, "twice_daily", hour="9,17", day_of_week="mon-fri")
        """
        job = self._scheduler.add_job(
            func,
            trigger="cron",
            second=second,
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=day_of_week,
            id=job_id,
            args=args,
            kwargs=kwargs or {},
            replace_existing=True,
        )

        log.info(
            "JobScheduler: '{}' scheduled with cron (hour={} minute={} day_of_week={})",
            job_id, hour, minute, day_of_week
        )
        return job

    def pause_job(self, job_id: str) -> bool:
        """
        Pauses a job — it won't fire until resumed.
        Useful for temporarily disabling a monitor without removing it.

        Args:
            job_id: the job to pause

        Returns:
            True if paused, False if job not found
        """
        try:
            self._scheduler.pause_job(job_id)
            log.info("JobScheduler: '{}' paused", job_id)
            return True
        except Exception as e:
            log.error("JobScheduler.pause_job failed for '{}': {}", job_id, str(e))
            return False

    def resume_job(self, job_id: str) -> bool:
        """
        Resumes a paused job.

        Args:
            job_id: the job to resume

        Returns:
            True if resumed, False if job not found
        """
        try:
            self._scheduler.resume_job(job_id)
            log.info("JobScheduler: '{}' resumed", job_id)
            return True
        except Exception as e:
            log.error("JobScheduler.resume_job failed for '{}': {}", job_id, str(e))
            return False

    def remove_job(self, job_id: str) -> bool:
        """
        Permanently removes a job from the scheduler.

        Args:
            job_id: the job to remove

        Returns:
            True if removed, False if job not found
        """
        try:
            self._scheduler.remove_job(job_id)
            log.info("JobScheduler: '{}' removed", job_id)
            return True
        except Exception as e:
            log.error("JobScheduler.remove_job failed for '{}': {}", job_id, str(e))
            return False

    def get_jobs(self) -> list[dict]:
        """
        Returns a summary of all scheduled jobs.

        Returns:
            list of dicts with job id, next_run, trigger info
        """
        jobs = []
        for job in self._scheduler.get_jobs():
            next_run = job.next_run_time
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run": next_run.strftime("%Y-%m-%d %H:%M:%S %Z") if next_run else "paused",
                "trigger": str(job.trigger),
            })
        return jobs

    def get_job_history(self) -> list[dict]:
        """
        Returns the execution history of all jobs this session.
        Tracks successes, failures, and missed executions.
        """
        return list(self._job_history)

    async def wait(self) -> None:
        """
        Keeps the scheduler running until interrupted.
        Use this in a script that should run indefinitely.

        Usage:
            scheduler = JobScheduler()
            await scheduler.start()
            scheduler.run_interval(my_job, "job", hours=1)
            await scheduler.wait()   # blocks here until Ctrl+C
        """
        log.info("JobScheduler: running — press Ctrl+C to stop")
        try:
            while self._running:
                await asyncio.sleep(1)
        except (KeyboardInterrupt, asyncio.CancelledError):
            log.info("JobScheduler: shutdown requested")
            await self.stop()

    # ── Event listeners ───────────────────────────────────────────────────────

    def _on_job_executed(self, event) -> None:
        """Called by APScheduler after a job completes successfully."""
        log.info(
            "JobScheduler: '{}' executed successfully (scheduled: {})",
            event.job_id,
            event.scheduled_run_time.strftime("%H:%M:%S") if event.scheduled_run_time else "N/A"
        )
        self._job_history.append({
            "job_id": event.job_id,
            "status": "success",
            "run_time": event.scheduled_run_time.isoformat() if event.scheduled_run_time else None,
        })

    def _on_job_error(self, event) -> None:
        """Called by APScheduler when a job raises an exception."""
        log.error(
            "JobScheduler: '{}' failed with error: {}",
            event.job_id,
            str(event.exception)
        )
        self._job_history.append({
            "job_id": event.job_id,
            "status": "error",
            "error": str(event.exception),
            "run_time": event.scheduled_run_time.isoformat() if event.scheduled_run_time else None,
        })

    def _on_job_missed(self, event) -> None:
        """Called by APScheduler when a job was missed (took longer than interval)."""
        log.warning(
            "JobScheduler: '{}' missed its scheduled run at {}",
            event.job_id,
            event.scheduled_run_time.strftime("%H:%M:%S") if event.scheduled_run_time else "N/A"
        )
        self._job_history.append({
            "job_id": event.job_id,
            "status": "missed",
            "run_time": event.scheduled_run_time.isoformat() if event.scheduled_run_time else None,
        })

    @property
    def is_running(self) -> bool:
        """True if the scheduler is currently active."""
        return self._running

    def __repr__(self) -> str:
        jobs = self._scheduler.get_jobs()
        return f"JobScheduler(running={self._running}, jobs={len(jobs)})"
