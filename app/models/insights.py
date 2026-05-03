from pydantic import BaseModel
from typing import List, Optional


class WeekPlan(BaseModel):
    week: int
    theme: str
    topics: List[str]
    patterns: List[str]
    example_problems: List[str]


class InsightsResponse(BaseModel):
    summary: str
    strengths: List[str]
    improvements: List[str]
    study_plan: List[WeekPlan]
    target_company: Optional[str] = None
