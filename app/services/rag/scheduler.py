from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI

from app.services.rag.embedder import get_collection_stats
from app.services.rag.retriever import is_rag_available
from app.utils.logger import get_logger, log_event

logger = get_logger(__name__)

_scheduler = AsyncIOScheduler()


async def run_weekly_pipeline() -> None:
    if await is_rag_available():
        log_event(logger, "info", "pipeline_start", mode="evals_only")
        from app.evals.harness import run_evals
        await run_evals()
    else:
        log_event(
            logger, "warning", "rag_empty",
            message="rag_empty — run scrape_local.py to populate ChromaDB",
        )


async def _log_startup_stats() -> None:
    stats = get_collection_stats()
    log_event(
        logger, "info", "rag_status_on_startup",
        total_problems=stats["total_problems"],
        last_updated=stats.get("last_updated", "never"),
    )


def start_scheduler(app: FastAPI) -> None:
    _scheduler.add_job(
        run_weekly_pipeline,
        CronTrigger(day_of_week="sun", hour=2, minute=0, timezone="UTC"),
        id="weekly_rag_pipeline",
        replace_existing=True,
    )
    _scheduler.add_job(
        _log_startup_stats,
        "date",
        id="startup_rag_status",
    )
    _scheduler.start()
    log_event(logger, "info", "scheduler_started", jobs=["weekly_rag_pipeline"])


def shutdown_scheduler() -> None:
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
        log_event(logger, "info", "scheduler_stopped")
