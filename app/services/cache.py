import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from app.utils.logger import get_logger, log_event

logger = get_logger(__name__)

CACHE_TTL_SECONDS = 60 * 60 * 24  # 24 hours

USE_REDIS = bool(os.getenv("UPSTASH_REDIS_URL"))

if USE_REDIS:
    from upstash_redis import Redis
    _redis = Redis(
        url=os.getenv("UPSTASH_REDIS_URL"),
        token=os.getenv("UPSTASH_REDIS_TOKEN"),
    )
else:
    _redis = None

# ---------------------------------------------------------------------------
# In-memory fallback (local dev without Redis)
# ---------------------------------------------------------------------------

_CACHE: Dict[str, Tuple[Any, float]] = {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _deserialize(key: str, data: dict) -> Any:
    """Reconstruct the correct Pydantic model from a raw dict based on cache key prefix."""
    if key.startswith("analytics:"):
        from app.models.schemas import AnalyticsResponse
        return AnalyticsResponse(**data)
    if key.startswith("insights:"):
        from app.models.insights import InsightsResponse
        return InsightsResponse(**data)
    return data


def get_cached(key: str) -> Any:
    if USE_REDIS:
        try:
            raw = _redis.get(key)
            if raw is not None:
                return _deserialize(key, json.loads(raw))
        except Exception as e:
            log_event(logger, "warning", "redis_get_failed", key=key, error=repr(e))

    entry = _CACHE.get(key)
    if entry is None:
        return None
    value, timestamp = entry
    if time.time() - timestamp > CACHE_TTL_SECONDS:
        del _CACHE[key]
        return None
    return value


def get_cache_metadata(key: str) -> Optional[str]:
    """Return the cached_at ISO timestamp for a key, or None if missing/expired."""
    meta_key = f"{key}:meta"

    if USE_REDIS:
        try:
            raw = _redis.get(meta_key)
            if raw is None:
                return None
            meta = json.loads(raw)
            return meta.get("cached_at")
        except Exception as e:
            log_event(logger, "warning", "redis_get_failed", key=meta_key, error=repr(e))
            return None

    entry = _CACHE.get(meta_key)
    if entry is None:
        return None
    value, timestamp = entry
    if time.time() - timestamp > CACHE_TTL_SECONDS:
        del _CACHE[meta_key]
        return None
    return value.get("cached_at")


def set_cached(key: str, value: Any) -> None:
    # Serialize Pydantic models; fall back to direct JSON for plain dicts
    if hasattr(value, "model_dump"):
        payload = json.dumps(value.model_dump())
    else:
        payload = json.dumps(value)

    cached_at = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta_payload = json.dumps({"cached_at": cached_at})
    meta_key = f"{key}:meta"

    if USE_REDIS:
        try:
            _redis.setex(key, CACHE_TTL_SECONDS, payload)
            _redis.setex(meta_key, CACHE_TTL_SECONDS, meta_payload)
        except Exception as e:
            log_event(logger, "warning", "redis_set_failed", key=key, error=repr(e))
        return

    now = time.time()
    _CACHE[key] = (value, now)
    _CACHE[meta_key] = ({"cached_at": cached_at}, now)


def clear_cache() -> int:
    if USE_REDIS:
        try:
            keys = _redis.keys("*")
            if keys:
                _redis.delete(*keys)
            return len(keys)
        except Exception as e:
            log_event(logger, "warning", "redis_clear_failed", error=repr(e))
            return 0

    count = len(_CACHE)
    _CACHE.clear()
    return count


def clear_user_cache(username: str) -> list:
    removed: list = []

    companies = ["meta", "google", "amazon", "microsoft",
                 "apple", "netflix", "uber", "bloomberg", "none"]

    key_patterns = [
        f"analytics:{username}",
        f"analytics:{username}:meta",
    ]
    for company in companies:
        key_patterns.append(f"insights:{username}:{company}")
        key_patterns.append(f"insights:{username}:{company}:meta")

    if USE_REDIS:
        try:
            for key in key_patterns:
                result = _redis.delete(key)
                if result:
                    removed.append(key)
                    log_event(logger, "debug", "redis_key_deleted", key=key)
        except Exception as e:
            log_event(logger, "warning", "redis_clear_failed", username=username, error=repr(e))

    in_memory_keys = [k for k in list(_CACHE.keys()) if username in k]
    for key in in_memory_keys:
        del _CACHE[key]
        removed.append(f"memory:{key}")

    log_event(logger, "info", "cache_cleared",
              username=username, removed_count=len(removed), removed_keys=removed)

    return removed
