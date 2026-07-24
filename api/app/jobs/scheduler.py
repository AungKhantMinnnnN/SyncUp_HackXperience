"""APScheduler maintenance sweeps. Runs inside the same FastAPI process (no separate
worker), started from app/main.py's lifespan and stopped alongside it.

Currently two jobs, both from the resources module:
  * expire_holds — releases holds past their 30-minute TTL, every 5 minutes
  * mark_overdue_checkouts — flags checked-out reservations more than 24h past their
    window end, on the same cadence (no reason to run a second scheduler for it)

Each job opens its own session via with_session() — jobs aren't in a request scope —
and the underlying service functions commit their own transaction (see service.py's
"standalone operations" section), so a failure in one run can't leave a half-applied
sweep.
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.db import with_session
from app.features.resources import service

logger = logging.getLogger("syncup.jobs.scheduler")

_scheduler: AsyncIOScheduler | None = None


async def _run_expire_holds() -> None:
    try:
        await with_session(service.expire_holds)
    except Exception:
        logger.exception("expire_holds sweep failed")


async def _run_mark_overdue() -> None:
    try:
        await with_session(service.mark_overdue_checkouts)
    except Exception:
        logger.exception("mark_overdue_checkouts sweep failed")


def start_jobs() -> AsyncIOScheduler:
    global _scheduler
    scheduler = AsyncIOScheduler()
    scheduler.add_job(_run_expire_holds, "interval", minutes=5, id="expire_holds")
    scheduler.add_job(_run_mark_overdue, "interval", minutes=5, id="mark_overdue_checkouts")
    scheduler.start()
    _scheduler = scheduler
    logger.info("scheduler started: expire_holds + mark_overdue_checkouts every 5 min")
    return scheduler


def stop_jobs() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
