import httpx
from fastapi import APIRouter, HTTPException
from app.models.schemas import AnalyzeResponse
from app.services.leetcode import fetch_skill_data, fetch_progress_data
from app.services.analytics import compute_skill_topics, compute_signals
from app.models.insights import InsightsResponse
from app.services.llm import generate_llm_insights
from app.services.cache import get_cached_insights, set_cached_insights


router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/analyze/{username}", response_model=AnalyzeResponse)
async def analyze_user(username: str):
    try:
        skill_data = await fetch_skill_data(username)
        progress_data = await fetch_progress_data(username)

        topics = compute_skill_topics(skill_data)
        signals = compute_signals(topics)

        progress_root = progress_data["numAcceptedQuestions"]

        def parse_progress(difficulty: str):
            solved = next(
                x["count"] for x in progress_root["numAcceptedQuestions"]
                if x["difficulty"] == difficulty
            )
            failed = next(
                x["count"] for x in progress_root["numFailedQuestions"]
                if x["difficulty"] == difficulty
            )
            untouched = next(
                x["count"] for x in progress_root["numUntouchedQuestions"]
                if x["difficulty"] == difficulty
            )
            percentile = next(
                x["percentage"] for x in progress_root["userSessionBeatsPercentage"]
                if x["difficulty"] == difficulty
            )

            return {
                "difficulty": difficulty,
                "solved": solved,
                "failed": failed,
                "untouched": untouched,
                "percentile": percentile
            }

        return {
            "username": username,
            "progress": {
                "easy": parse_progress("EASY"),
                "medium": parse_progress("MEDIUM"),
                "hard": parse_progress("HARD"),
            },
            "skills": {
                "topics": topics
            },
            "signals": signals
        }

    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="LeetCode API unavailable")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



@router.post("/insights/{username}", response_model=InsightsResponse)
async def get_insights(username: str):

    # Check cache first
    cached = get_cached_insights(username)
    if cached:
        return cached

    # Reuse existing analyze logic
    analysis = await analyze_user(username)
    print(">>> ANALYSIS GENERATED")

    try:
        insights = await generate_llm_insights(analysis)
        set_cached_insights(username, insights)
        print(">>> LLM FUNCTION RETURNED")
        return insights

    except ValueError:
        raise HTTPException(status_code=500, detail="Invalid AI response")
    except Exception:
        raise HTTPException(status_code=500, detail="AI insights unavailable")
