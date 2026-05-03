from pydantic import BaseModel
from typing import List, Dict, Optional


class DifficultyStats(BaseModel):
    solved: int
    attempted: int
    total: int


class TopicStat(BaseModel):
    name: str
    solved: int
    category: str  # fundamental | intermediate | advanced


class SubmissionEntry(BaseModel):
    title: str
    slug: str
    timestamp: int
    status: str
    language: str


class ContestInfo(BaseModel):
    rating: float
    global_rank: int
    attended: int
    top_percentage: float
    history: List


class ConsistencyInfo(BaseModel):
    current_streak: int
    longest_streak: int
    active_days_30: int
    active_days_90: int
    consistency_score: float
    submission_calendar: Dict[str, int]  # epoch string → submission count


class LanguageStat(BaseModel):
    language: str
    solved: int


class AnalyticsResponse(BaseModel):
    username: str
    difficulty: Dict[str, DifficultyStats]   # keys: easy, medium, hard
    topics: List[TopicStat]
    strong_topics: List[TopicStat]
    weak_topics: List[TopicStat]
    consistency: ConsistencyInfo
    languages: List[LanguageStat]
    recent_submissions: List[SubmissionEntry]
    contest: Optional[ContestInfo]
    cached_at: Optional[str] = None
