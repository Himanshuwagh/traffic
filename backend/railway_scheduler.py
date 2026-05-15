from __future__ import annotations

import logging
import os
from datetime import timezone

from apscheduler.schedulers.blocking import BlockingScheduler

try:
    from .ingest_tomtom_traffic import run_ingestion
except ImportError:
    from ingest_tomtom_traffic import run_ingestion  # type: ignore[no-redef]


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger(__name__)


def _scheduler_timezone():
    timezone_name = os.getenv("TOMTOM_SCHEDULER_TIMEZONE", "UTC").strip() or "UTC"
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(timezone_name)
    except Exception:
        log.warning("Invalid TOMTOM_SCHEDULER_TIMEZONE=%s, falling back to UTC", timezone_name)
        return timezone.utc


def run_scheduled_ingest() -> None:
    log.info("Starting scheduled TomTom ingestion run")
    try:
        totals = run_ingestion(mode="auto")
        log.info("Scheduled TomTom ingestion completed: %s", totals)
    except Exception as exc:
        log.exception("Scheduled TomTom ingestion failed: %s", exc)


def main() -> None:
    minute = int(os.getenv("TOMTOM_SCHEDULER_MINUTE", "0"))
    scheduler = BlockingScheduler(timezone=_scheduler_timezone())
    scheduler.add_job(
        run_scheduled_ingest,
        trigger="cron",
        minute=minute,
        id="tomtom-hourly-ingestion",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
        replace_existing=True,
    )
    log.info("Railway scheduler started; hourly ingest runs at minute %s", minute)
    scheduler.start()


if __name__ == "__main__":
    main()
