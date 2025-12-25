from datetime import datetime
from typing import List


def consistency_score(dates: List[str]) -> float:
    if len(dates) < 2:
        return 0.0

    parsed = sorted(datetime.fromisoformat(d) for d in dates)
    gaps = [(parsed[i] - parsed[i - 1]).days for i in range(1, len(parsed))]

    avg_gap = sum(gaps) / len(gaps)
    return round(max(0.0, 1.0 - avg_gap / 7), 2)
