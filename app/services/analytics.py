import json
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from app.models.schemas import (
    AnalyticsResponse,
    ConsistencyInfo,
    ContestInfo,
    DifficultyStats,
    LanguageStat,
    SubmissionEntry,
    TopicStat,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Difficulty
# ---------------------------------------------------------------------------

def _build_difficulty(raw: dict) -> "dict[str, DifficultyStats]":
    progress_root = raw.get("progress", {}).get("numAcceptedQuestions", {})
    solved_data   = raw.get("solved", {})

    def _count(arr: list, difficulty: str) -> int:
        return next(
            (x["count"] for x in arr if x.get("difficulty", "").upper() == difficulty),
            0,
        )

    accepted  = progress_root.get("numAcceptedQuestions",  [])
    failed    = progress_root.get("numFailedQuestions",    [])
    untouched = progress_root.get("numUntouchedQuestions", [])

    result = {}
    for label in ("EASY", "MEDIUM", "HARD"):
        solved      = _count(accepted,  label)
        failed_n    = _count(failed,    label)
        untouched_n = _count(untouched, label)
        total       = solved + failed_n + untouched_n
        attempted   = solved + failed_n

        # Fall back to /solved when progress data is absent
        if total == 0:
            key    = label.lower()
            solved    = solved_data.get(f"{key}Solved", 0)
            attempted = solved
            total     = solved_data.get(f"total{label.capitalize()}", 0)

        result[label.lower()] = DifficultyStats(
            solved=solved,
            attempted=attempted,
            total=total,
        )

    return result


# ---------------------------------------------------------------------------
# Topics
# ---------------------------------------------------------------------------

def _build_topics(raw: dict) -> "tuple[list[TopicStat], list[TopicStat], list[TopicStat]]":
    skill = raw.get("skill", {})

    all_topics = []
    for category in ("fundamental", "intermediate", "advanced"):
        for entry in skill.get(category, []):
            all_topics.append(TopicStat(
                name=entry["tagName"],
                solved=entry["problemsSolved"],
                category=category,
            ))

    all_topics.sort(key=lambda t: t.solved, reverse=True)

    strong = all_topics[:5]
    strong_names = {t.name for t in strong}

    weak_candidates = [t for t in all_topics if t.solved >= 2 and t.name not in strong_names]
    weak = weak_candidates[-5:] if len(weak_candidates) >= 5 else weak_candidates

    return all_topics, strong, weak


# ---------------------------------------------------------------------------
# Consistency / streaks
# ---------------------------------------------------------------------------

def _build_consistency(raw: dict) -> ConsistencyInfo:
    calendar_raw = raw.get("calendar", {})

    # Use the pre-computed streak from the API — it accounts for timezone and
    # partial-day logic that our local recomputation gets wrong by ~1.
    current_streak = int(calendar_raw.get("streak", 0))

    cal_str = calendar_raw.get("submissionCalendar", "{}")
    try:
        cal: dict[str, Any] = json.loads(cal_str) if isinstance(cal_str, str) else cal_str
    except (json.JSONDecodeError, TypeError):
        cal = {}

    active_dates = set()
    for ts_str in cal:
        try:
            dt = datetime.fromtimestamp(int(ts_str), tz=timezone.utc).date()
            active_dates.add(dt)
        except (ValueError, OSError):
            continue

    today = datetime.now(tz=timezone.utc).date()

    # Longest streak — derive from calendar data
    longest_streak = 0
    run = 0
    for d in sorted(active_dates):
        if run == 0:
            run = 1
        elif d - timedelta(days=1) in active_dates:
            run += 1
        else:
            run = 1
        longest_streak = max(longest_streak, run)

    # Ensure longest is never less than current
    longest_streak = max(longest_streak, current_streak)

    active_days_30 = sum(1 for d in active_dates if (today - d).days < 30)
    active_days_90 = sum(1 for d in active_dates if (today - d).days < 90)

    raw_score = (active_days_30 / 30) * 60 + (active_days_90 / 90) * 40
    consistency_score = round(min(raw_score, 100.0), 1)

    submission_calendar = {ts: int(count) for ts, count in cal.items()}

    return ConsistencyInfo(
        current_streak=current_streak,
        longest_streak=longest_streak,
        active_days_30=active_days_30,
        active_days_90=active_days_90,
        consistency_score=consistency_score,
        submission_calendar=submission_calendar,
    )


# ---------------------------------------------------------------------------
# Languages
# ---------------------------------------------------------------------------

def _build_languages(raw: dict) -> "list[LanguageStat]":
    entries = raw.get("language", {}).get("languageProblemCount", [])
    return [
        LanguageStat(language=e["languageName"], solved=e["problemsSolved"])
        for e in entries
    ]


# ---------------------------------------------------------------------------
# Recent submissions
# ---------------------------------------------------------------------------

def _build_submissions(raw: dict) -> "list[SubmissionEntry]":
    entries = raw.get("ac_submissions", {}).get("submission", [])
    result = []
    for e in entries[:20]:
        result.append(SubmissionEntry(
            title=e.get("title", ""),
            slug=e.get("titleSlug", ""),
            timestamp=int(e.get("timestamp", 0)),
            status=e.get("statusDisplay", ""),
            language=e.get("lang", ""),
        ))
    return result


# ---------------------------------------------------------------------------
# Contest
# ---------------------------------------------------------------------------

def _build_contest(raw: dict) -> Optional[ContestInfo]:
    c = raw.get("contest", {})
    if not c:
        return None

    history_raw = c.get("contestParticipation", [])[-10:]
    history = [
        {
            "title":   entry.get("contest", {}).get("title", ""),
            "start":   entry.get("contest", {}).get("startTime", 0),
            "rating":  entry.get("rating", 0.0),
            "ranking": entry.get("ranking", 0),
            "solved":  entry.get("problemsSolved", 0),
            "total":   entry.get("totalProblems", 0),
        }
        for entry in history_raw
    ]

    return ContestInfo(
        rating=c.get("contestRating", 0.0),
        global_rank=c.get("contestGlobalRanking", 0),
        attended=c.get("contestAttend", 0),
        top_percentage=c.get("contestTopPercentage", 0.0),
        history=history,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def compute_analytics(raw: dict) -> AnalyticsResponse:
    username = raw.get("username", "")

    logger.debug("raw keys: %s", [k for k in raw if k != "username"])
    logger.debug("profile keys: %s", list(raw.get("profile", {}).keys()))
    logger.debug("skill keys: %s", list(raw.get("skill", {}).keys()))
    logger.debug("calendar keys: %s", list(raw.get("calendar", {}).keys()))
    logger.debug("language keys: %s", list(raw.get("language", {}).keys()))
    logger.debug("ac_submissions keys: %s", list(raw.get("ac_submissions", {}).keys()))
    logger.debug("progress keys: %s", list(raw.get("progress", {}).keys()))

    difficulty             = _build_difficulty(raw)
    topics, strong, weak   = _build_topics(raw)
    consistency            = _build_consistency(raw)
    languages              = _build_languages(raw)
    recent_submissions     = _build_submissions(raw)
    contest                = _build_contest(raw)

    return AnalyticsResponse(
        username=username,
        difficulty=difficulty,
        topics=topics,
        strong_topics=strong,
        weak_topics=weak,
        consistency=consistency,
        languages=languages,
        recent_submissions=recent_submissions,
        contest=contest,
    )
