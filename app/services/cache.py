import time
from typing import Dict, Tuple

# username -> (response, timestamp)
INSIGHTS_CACHE: Dict[str, Tuple[dict, float]] = {}

CACHE_TTL_SECONDS = 60 * 60 * 24  # 24 hours


def get_cached_insights(username: str):
    if username not in INSIGHTS_CACHE:
        return None

    cached_response, timestamp = INSIGHTS_CACHE[username]
    if time.time() - timestamp > CACHE_TTL_SECONDS:
        del INSIGHTS_CACHE[username]
        return None

    return cached_response


def set_cached_insights(username: str, insights: dict):
    INSIGHTS_CACHE[username] = (insights, time.time())
