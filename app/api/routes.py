import os
from pathlib import Path
from typing import Optional

import posthog
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.models.insights import InsightsResponse
from app.models.schemas import AnalyticsResponse
from app.services.analytics import compute_analytics
from app.services.cache import get_cached, get_cache_metadata, set_cached, clear_cache, clear_user_cache
from app.services.leetcode import fetch_all
from app.services.llm import generate_llm_insights
from app.services.rag.retriever import retrieve_problems, format_for_prompt, is_rag_available
from app.utils.logger import get_logger, log_event

logger = get_logger(__name__)

router = APIRouter()


class InsightsRequest(BaseModel):
    target_company: Optional[str] = None


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@router.get("/health")
async def health():
    posthog.capture(distinct_id="test", event="health_check")
    posthog.flush()
    return {"status": "ok"}


_EVALS_RESULTS_DIR = Path(__file__).resolve().parent.parent / "evals" / "results"


@router.get("/evals/latest")
async def get_latest_evals(x_admin_key: Optional[str] = Header(default=None)):
    admin_secret = os.getenv("ADMIN_SECRET")
    if not admin_secret or x_admin_key != admin_secret:
        raise HTTPException(status_code=403, detail="Forbidden")
    result_files = sorted(_EVALS_RESULTS_DIR.glob("*.json"))
    if not result_files:
        raise HTTPException(status_code=404, detail="No eval results found")
    import json
    return JSONResponse(content=json.loads(result_files[-1].read_text()))


class IngestRequest(BaseModel):
    problems: list[dict]


@router.post("/admin/rag/ingest")
async def ingest_rag_problems(body: IngestRequest, x_admin_key: Optional[str] = Header(default=None)):
    admin_secret = os.getenv("ADMIN_SECRET")
    if not admin_secret or x_admin_key != admin_secret:
        raise HTTPException(status_code=403, detail="Forbidden")
    count = len(body.problems)
    log_event(logger, "info", "ingest_received", count=count)
    try:
        from app.services.rag.embedder import embed_and_store
        await embed_and_store(body.problems)
        return {"status": "ok", "problems_ingested": count}
    except Exception as e:
        log_event(logger, "error", "ingest_failed", count=count, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to embed and store problems")


@router.post("/admin/rag/trigger")
async def trigger_rag_pipeline(x_admin_key: Optional[str] = Header(default=None)):
    admin_secret = os.getenv("ADMIN_SECRET")
    if not admin_secret or x_admin_key != admin_secret:
        raise HTTPException(status_code=403, detail="Forbidden")
    import asyncio
    from app.services.rag.scheduler import run_weekly_pipeline
    asyncio.create_task(run_weekly_pipeline())
    return {"status": "pipeline triggered", "message": "Check logs for progress"}


@router.post("/admin/cache/clear")
async def admin_clear_cache(x_admin_key: Optional[str] = Header(default=None)):
    admin_secret = os.getenv("ADMIN_SECRET")
    if not admin_secret or x_admin_key != admin_secret:
        raise HTTPException(status_code=403, detail="Forbidden")
    count = clear_cache()
    logger.info("Cache cleared: %d entries removed", count)
    return {"cleared": count}


@router.delete("/cache/{username}")
async def bust_user_cache(username: str):
    removed = clear_user_cache(username)
    log_event(logger, "info", "cache_bust", username=username, removed_keys=removed)
    posthog.capture(
        distinct_id=username,
        event="data_refreshed",
        properties={"username": username},
    )
    posthog.flush()
    return {"username": username, "removed": removed}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_analytics(username: str) -> AnalyticsResponse:
    """Return analytics from cache or fetch+compute fresh, then cache."""
    cache_key = f"analytics:{username}"
    cached = get_cached(cache_key)
    if cached is not None:
        log_event(logger, "info", "cache_hit", cache_key=cache_key, username=username)
        return cached

    log_event(logger, "info", "cache_miss", cache_key=cache_key, username=username)
    raw = await fetch_all(username)
    analytics = compute_analytics(raw)

    # Don't cache a result where the upstream API returned nothing useful —
    # all zeros means every endpoint was rate-limited or failed.
    total_solved = sum(d.solved for d in analytics.difficulty.values())
    if total_solved == 0 and not analytics.topics and not analytics.recent_submissions:
        logger.warning("Skipping cache for %s — upstream data appears empty (rate-limited?)", username)
    else:
        set_cached(cache_key, analytics)
        logger.info("Analytics computed and cached for %s", username)

    return analytics


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/analyze/{username}", response_model=AnalyticsResponse)
async def analyze_user(username: str):
    log_event(logger, "info", "analyze_request", username=username)
    try:
        cache_key = f"analytics:{username}"
        cached_at = get_cache_metadata(cache_key)
        was_cached = cached_at is not None
        analytics = await _get_analytics(username)
        if cached_at is None:
            cached_at = get_cache_metadata(cache_key)
        analytics.cached_at = cached_at
        total = (
            analytics.difficulty["easy"].solved
            + analytics.difficulty["medium"].solved
            + analytics.difficulty["hard"].solved
        )
        try:
            posthog.capture(
                distinct_id=username,
                event="username_analyzed",
                properties={
                    "username": username,
                    "cache_hit": was_cached,
                    "total_solved": total,
                    "easy_solved": analytics.difficulty["easy"].solved,
                    "medium_solved": analytics.difficulty["medium"].solved,
                    "hard_solved": analytics.difficulty["hard"].solved,
                    "hard_ratio": round(analytics.difficulty["hard"].solved / total * 100, 1) if total > 0 else 0,
                    "consistency_score": analytics.consistency.consistency_score,
                    "current_streak": analytics.consistency.current_streak,
                    "top_language": analytics.languages[0].language if analytics.languages else "unknown",
                    "contest_rating": analytics.contest.rating if analytics.contest else 0,
                    "has_contest_history": analytics.contest is not None and analytics.contest.attended > 0,
                    "skill_level": "beginner" if total < 100 else "intermediate" if total < 300 else "advanced" if total < 600 else "expert",
                    "strong_topics": [t.name for t in analytics.strong_topics[:3]],
                    "weak_topics": [t.name for t in analytics.weak_topics[:3]],
                },
            )
            posthog.flush()
        except Exception as e:
            log_event(logger, "warning", "posthog_capture_failed", error=str(e))
        return analytics
    except Exception as e:
        logger.error("Analytics failed for %s: %r", username, e)
        raise HTTPException(status_code=502, detail="Failed to fetch or compute analytics")


@router.post("/insights/{username}", response_model=InsightsResponse)
async def get_insights(username: str, body: InsightsRequest = InsightsRequest()):
    target_company = body.target_company
    log_event(logger, "info", "insights_request", username=username, target_company=target_company)
    cache_key = f"insights:{username}:{target_company or 'none'}"

    cached = get_cached(cache_key)
    if cached is not None:
        logger.info("Insights cache hit for %s (company=%r)", username, target_company)
        try:
            analytics = await _get_analytics(username)
            total_solved = sum(d.solved for d in analytics.difficulty.values())
        except Exception:
            total_solved = 0
        try:
            posthog.capture(
                distinct_id=username,
                event="insights_generated",
                properties={
                    "username": username,
                    "target_company": target_company or "none",
                    "cache_hit": True,
                    "skill_level": "beginner" if total_solved < 100 else "intermediate" if total_solved < 300 else "advanced" if total_solved < 600 else "expert",
                    "has_target_company": target_company is not None,
                },
            )
            posthog.flush()
        except Exception as e:
            log_event(logger, "warning", "posthog_capture_failed", error=str(e))
        return cached

    try:
        analytics = await _get_analytics(username)
    except Exception as e:
        logger.error("Analytics fetch failed for insights request %s: %r", username, e)
        raise HTTPException(status_code=502, detail="Failed to fetch analytics for insights")

    try:
        rag_context = None
        if target_company and await is_rag_available():
            try:
                weak_topic_names = [t.name for t in analytics.weak_topics]
                total_solved = (
                    analytics.difficulty.get("easy").solved
                    + analytics.difficulty.get("medium").solved
                    + analytics.difficulty.get("hard").solved
                )
                if total_solved < 100:
                    difficulty_focus = "easy medium"
                elif total_solved < 400:
                    difficulty_focus = "medium"
                else:
                    difficulty_focus = "medium hard"

                problems = await retrieve_problems(
                    weak_topics=weak_topic_names,
                    target_company=target_company,
                    difficulty_focus=difficulty_focus,
                    n_results=15,
                )
                if problems:
                    rag_context = format_for_prompt(problems, n_per_week=3)
                    log_event(
                        logger, "info", "rag_context_built",
                        username=username,
                        company=target_company,
                        problems_count=len(problems),
                    )
            except Exception as e:
                log_event(
                    logger, "warning", "rag_retrieval_failed",
                    username=username,
                    company=target_company,
                    error=str(e),
                )

        insights = await generate_llm_insights(analytics, target_company, rag_context)
        set_cached(cache_key, insights)
        logger.info("Insights cached for %s (company=%r)", username, target_company)
        total_solved = sum(d.solved for d in analytics.difficulty.values())
        try:
            posthog.capture(
                distinct_id=username,
                event="insights_generated",
                properties={
                    "username": username,
                    "target_company": target_company or "none",
                    "cache_hit": False,
                    "skill_level": "beginner" if total_solved < 100 else "intermediate" if total_solved < 300 else "advanced" if total_solved < 600 else "expert",
                    "has_target_company": target_company is not None,
                },
            )
            posthog.flush()
        except Exception as e:
            log_event(logger, "warning", "posthog_capture_failed", error=str(e))
        return insights
    except Exception as e:
        logger.error("LLM insights failed for %s: %r", username, e)
        raise HTTPException(status_code=500, detail="Failed to generate AI insights")
