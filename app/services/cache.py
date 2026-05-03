import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

_CACHE: Dict[str, Tuple[Any, float]] = {}

CACHE_TTL_SECONDS = 60 * 60 * 24  # 24 hours


def get_cached(key: str) -> Any:
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
    entry = _CACHE.get(key)
    if entry is None:
        return None
    value, timestamp = entry
    if time.time() - timestamp > CACHE_TTL_SECONDS:
        del _CACHE[key]
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def set_cached(key: str, value: Any) -> None:
    _CACHE[key] = (value, time.time())


def clear_cache() -> int:
    count = len(_CACHE)
    _CACHE.clear()
    return count


def clear_user_cache(username: str) -> list:
    keys = [k for k in list(_CACHE.keys()) if username.lower() in k.lower()]
    for k in keys:
        del _CACHE[k]
    return keys
