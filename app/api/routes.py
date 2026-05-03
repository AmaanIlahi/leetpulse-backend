import logging
from typing import Optional

import posthog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.models.insights import InsightsResponse
from app.models.schemas import AnalyticsResponse
from app.services.analytics import compute_analytics
from app.services.cache import get_cached, get_cache_metadata, set_cached, clear_cache, clear_user_cache
from app.services.leetcode import fetch_all
from app.services.llm import generate_llm_insights

logger = logging.getLogger(__name__)

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


@router.post("/admin/cache/clear")
async def admin_clear_cache():
    count = clear_cache()
    logger.info("Cache cleared: %d entries removed", count)
    return {"cleared": count}


@router.delete("/cache/{username}")
async def bust_user_cache(username: str):
    removed = clear_user_cache(username)
    logger.info("Cache busted for %s: %s", username, removed)
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
        logger.info("Analytics cache hit for %s", username)
        return cached

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
        return analytics
    except Exception as e:
        logger.error("Analytics failed for %s: %r", username, e)
        raise HTTPException(status_code=502, detail="Failed to fetch or compute analytics")


@router.post("/insights/{username}", response_model=InsightsResponse)
async def get_insights(username: str, body: InsightsRequest = InsightsRequest()):
    target_company = body.target_company
    cache_key = f"insights:{username}:{target_company or 'none'}"

    cached = get_cached(cache_key)
    if cached is not None:
        logger.info("Insights cache hit for %s (company=%r)", username, target_company)
        try:
            analytics = await _get_analytics(username)
            total_solved = sum(d.solved for d in analytics.difficulty.values())
        except Exception:
            total_solved = 0
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
        return cached

    try:
        analytics = await _get_analytics(username)
    except Exception as e:
        logger.error("Analytics fetch failed for insights request %s: %r", username, e)
        raise HTTPException(status_code=502, detail="Failed to fetch analytics for insights")

    try:
        insights = await generate_llm_insights(analytics, target_company)
        set_cached(cache_key, insights)
        logger.info("Insights cached for %s (company=%r)", username, target_company)
        total_solved = sum(d.solved for d in analytics.difficulty.values())
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
        return insights
    except Exception as e:
        logger.error("LLM insights failed for %s: %r", username, e)
        raise HTTPException(status_code=500, detail="Failed to generate AI insights")
