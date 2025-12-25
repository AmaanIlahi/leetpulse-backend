from pydantic import BaseModel
from typing import List, Dict


# ---------- Progress ----------

class DifficultyProgress(BaseModel):
    difficulty: str
    solved: int
    failed: int
    untouched: int
    percentile: float


class ProgressResponse(BaseModel):
    easy: DifficultyProgress
    medium: DifficultyProgress
    hard: DifficultyProgress


# ---------- Skills / Topics ----------

class TopicSkill(BaseModel):
    name: str
    solved: int
    level: str  # fundamental | intermediate | advanced


class SkillResponse(BaseModel):
    topics: List[TopicSkill]


# ---------- Signals ----------

class Signals(BaseModel):
    strong_topics: List[str]
    weak_topics: List[str]


# ---------- Final Analyze Response ----------

class AnalyzeResponse(BaseModel):
    username: str
    progress: ProgressResponse
    skills: SkillResponse
    signals: Signals
