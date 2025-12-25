from datetime import datetime
from typing import List


def consistency_score(activity_dates: List[str]) -> float:
    """
    Computes a consistency score based on gaps between activity dates.
    Higher score = more consistent practice.
    """
    if not activity_dates or len(activity_dates) < 2:
        return 0.0

    dates = sorted(datetime.fromisoformat(d) for d in activity_dates)

    gaps = [
        (dates[i] - dates[i - 1]).days
        for i in range(1, len(dates))
    ]

    avg_gap = sum(gaps) / len(gaps)

    # Normalize: weekly gap → score ~0
    score = max(0.0, 1.0 - (avg_gap / 7))
    return round(score, 2)
