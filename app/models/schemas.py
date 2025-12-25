from pydantic import BaseModel
from typing import List, Dict


class DifficultySplit(BaseModel):
    easy: int
    medium: int
    hard: int


class ProfileResponse(BaseModel):
    username: str
    total_solved: int
    acceptance_rate: float
    difficulty_split: DifficultySplit


class TopicStat(BaseModel):
    topic: str
    solved: int
    accuracy: float


class Signals(BaseModel):
    weak_topics: List[str]
    strong_topics: List[str]
    consistency_score: float


class AnalyzeResponse(BaseModel):
    profile: ProfileResponse
    topic_stats: List[TopicStat]
    signals: Signals
