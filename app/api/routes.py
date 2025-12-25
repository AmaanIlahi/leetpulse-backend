from fastapi import APIRouter
from app.models.schemas import AnalyzeResponse
from app.services.analytics import generate_signals


router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "ok"}

@router.get("/analyze/{username}", response_model=AnalyzeResponse)
async def analyze_user(username: str):
    topic_stats = [
        {"topic": "Arrays", "solved": 120, "accuracy": 0.71},
        {"topic": "Graphs", "solved": 31, "accuracy": 0.38},
        {"topic": "Dynamic Programming", "solved": 42, "accuracy": 0.41},
    ]

    activity_dates = [
        "2024-12-01",
        "2024-12-03",
        "2024-12-04",
        "2024-12-10",
        "2024-12-15",
    ]

    signals = generate_signals(topic_stats, activity_dates)

    return {
        "profile": {
            "username": username,
            "total_solved": 412,
            "acceptance_rate": 0.57,
            "difficulty_split": {
                "easy": 180,
                "medium": 190,
                "hard": 42
            }
        },
        "topic_stats": topic_stats,
        "signals": signals
    }
