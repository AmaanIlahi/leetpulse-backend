import httpx

BASE_URL = "https://alfa-leetcode-api.onrender.com"


async def fetch_skill_data(username: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{BASE_URL}/{username}/skill/")
        r.raise_for_status()
        return r.json()


async def fetch_progress_data(username: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{BASE_URL}/{username}/progress/")
        r.raise_for_status()
        return r.json()
