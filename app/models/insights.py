from pydantic import BaseModel
from typing import List


class FocusTopic(BaseModel):
    topic: str
    reason: str


class StudyDay(BaseModel):
    day: str
    task: str


class InsightsResponse(BaseModel):
    summary: str
    strengths: List[str]
    weaknesses: List[str]
    focus_topics: List[FocusTopic]
    study_plan: List[StudyDay]
