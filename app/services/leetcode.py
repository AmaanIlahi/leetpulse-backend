import asyncio
import time
import httpx

from app.utils.logger import get_logger, log_event

logger = get_logger(__name__)

BASE_URL = "https://alfa-leetcode-api.onrender.com"
TIMEOUT = 25.0

_semaphore = asyncio.Semaphore(3)


async def _get(client: httpx.AsyncClient, url: str, key: str) -> tuple[str, dict]:
    try:
        r = await client.get(url)
        r.raise_for_status()
        return key, r.json()
    except Exception as e:
        log_event(logger, "warning", "fetch_endpoint_error", endpoint=key, url=url, error=repr(e))
        return key, {}


async def _get_limited(client: httpx.AsyncClient, url: str, key: str, delay: float) -> tuple[str, dict]:
    await asyncio.sleep(delay)
    async with _semaphore:
        return await _get(client, url, key)


async def fetch_all(username: str) -> dict:
    endpoints = [
        (f"{BASE_URL}/{username}",                         "profile"),
        (f"{BASE_URL}/{username}/solved",                  "solved"),
        (f"{BASE_URL}/{username}/skill",                   "skill"),
        (f"{BASE_URL}/{username}/language",                "language"),
        (f"{BASE_URL}/{username}/acSubmission?limit=20",   "ac_submissions"),
        (f"{BASE_URL}/{username}/calendar",                "calendar"),
        (f"{BASE_URL}/{username}/contest",                 "contest"),
        (f"{BASE_URL}/{username}/progress",                "progress"),
    ]

    log_event(logger, "info", "fetch_start", username=username, endpoint_count=len(endpoints))
    t0 = time.monotonic()

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        results = await asyncio.gather(
            *(_get_limited(client, url, key, i * 0.5) for i, (url, key) in enumerate(endpoints))
        )

    data = {key: payload for key, payload in results}
    data["username"] = username

    failed = [key for key, payload in results if not payload]
    log_event(
        logger, "info", "fetch_complete",
        username=username,
        latency_ms=round((time.monotonic() - t0) * 1000),
        failed_endpoints=failed,
    )
    return data
