import asyncio
import os
from typing import Optional

import httpx

from app.utils.logger import get_logger, log_event

logger = get_logger(__name__)

_SESSION = os.getenv("LEETCODE_SESSION", "")
_CSRF = os.getenv("LEETCODE_CSRF_TOKEN", "")

COMPANY_CONFIGS: dict[str, dict] = {
    "meta": {
        "slug": "facebook-three-months",
        "url":  "https://leetcode.com/company/facebook/?favoriteSlug=facebook-three-months",
    },
    "google": {
        "slug": "google-thirty-days",
        "url":  "https://leetcode.com/company/google/?favoriteSlug=google-thirty-days",
    },
    "amazon": {
        "slug": "amazon-thirty-days",
        "url":  "https://leetcode.com/company/amazon/?favoriteSlug=amazon-thirty-days",
    },
    "microsoft": {
        "slug": "microsoft-three-months",
        "url":  "https://leetcode.com/company/microsoft/?favoriteSlug=microsoft-three-months",
    },
    "apple": {
        "slug": "apple-six-months",
        "url":  "https://leetcode.com/company/apple/?favoriteSlug=apple-six-months",
    },
    "netflix": {
        "slug": "netflix-all",
        "url":  "https://leetcode.com/company/netflix/?favoriteSlug=netflix-all",
    },
    "uber": {
        "slug": "uber-six-months",
        "url":  "https://leetcode.com/company/uber/?favoriteSlug=uber-six-months",
    },
    "bloomberg": {
        "slug": "bloomberg-three-months",
        "url":  "https://leetcode.com/company/bloomberg/?favoriteSlug=bloomberg-three-months",
    },
}

_GRAPHQL_URL = "https://leetcode.com/graphql"
_HEALTH_URL  = "https://leetcode.com/api/problems/all/"
_TIMEOUT     = 30.0

_QUERY = """
query problemsetQuestionListV2($filters: ProblemsetQuestionListFilterInput) {
  problemsetQuestionListV2(filters: $filters, limit: 100) {
    questions {
      title
      titleSlug
      difficulty
      topicTags { name }
      freqBar
    }
  }
}
"""


def _auth_headers() -> dict[str, str]:
    return {
        "Cookie":       f"LEETCODE_SESSION={_SESSION}; csrftoken={_CSRF}",
        "x-csrftoken":  _CSRF,
        "Content-Type": "application/json",
        "Referer":      "https://leetcode.com",
    }


async def check_cookie_health() -> bool:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False) as client:
            r = await client.get(_HEALTH_URL, headers=_auth_headers())
        healthy = r.status_code == 200
        log_event(logger, "info", "cookie_health_check", status_code=r.status_code, healthy=healthy)
        return healthy
    except Exception as e:
        log_event(logger, "warning", "cookie_health_check", healthy=False, error=repr(e))
        return False


async def fetch_company_problems(company: str) -> list[dict]:
    config = COMPANY_CONFIGS.get(company.lower())
    slug = config["slug"] if config else None
    if not slug:
        log_event(logger, "warning", "fetch_company_problems_skipped", company=company, reason="unknown company")
        return []

    payload = {
        "operationName": "problemsetQuestionListV2",
        "query":         _QUERY,
        "variables":     {"filters": {"favoriteSlug": slug}},
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.post(_GRAPHQL_URL, json=payload, headers=_auth_headers())
        r.raise_for_status()
        data = r.json()
        questions = (
            data.get("data", {})
                .get("problemsetQuestionListV2", {})
                .get("questions", [])
        )
        problems = [
            {
                "title":      q["title"],
                "slug":       q["titleSlug"],
                "difficulty": q["difficulty"],
                "tags":       [t["name"] for t in q.get("topicTags", [])],
                "company":    company.lower(),
                "freq_bar":   q.get("freqBar"),
            }
            for q in questions
        ]
        log_event(logger, "info", "fetch_company_problems_complete",
                  company=company, count=len(problems))
        return problems
    except Exception as e:
        log_event(logger, "error", "fetch_company_problems_failed",
                  company=company, slug=slug, error=repr(e))
        return []


async def scrape_all_companies() -> list[dict]:
    healthy = await check_cookie_health()
    if not healthy:
        log_event(
            logger, "error", "cookie_expired",
            message="LeetCode session cookie expired — update LEETCODE_SESSION secret on Fly.io",
        )
        return []

    results: list[list[dict]] = await asyncio.gather(
        *[fetch_company_problems(company) for company in COMPANY_CONFIGS]
    )

    all_problems: list[dict] = []
    per_company: dict[str, int] = {}
    for company, problems in zip(COMPANY_CONFIGS.keys(), results):
        per_company[company] = len(problems)
        all_problems.extend(problems)

    log_event(
        logger, "info", "scrape_complete",
        total=len(all_problems),
        per_company=per_company,
    )
    return all_problems