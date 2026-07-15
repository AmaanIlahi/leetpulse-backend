import os
import time

from openai import AsyncOpenAI

from app.services.rag.embedder import collection
from app.utils.logger import get_logger, log_event

logger = get_logger(__name__)

_openai     = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
_EMBED_MODEL = "text-embedding-3-small"


# ---------------------------------------------------------------------------
# Core retrieval
# ---------------------------------------------------------------------------

async def retrieve_problems(
    weak_topics: list[str],
    target_company: str,
    difficulty_focus: str,
    n_results: int = 20,
) -> list[dict]:
    query = (
        f"{' '.join(weak_topics)} {target_company} "
        f"{difficulty_focus} interview problems"
    )

    t0 = time.monotonic()

    embed_response = await _openai.embeddings.create(
        model=_EMBED_MODEL,
        input=[query],
    )
    query_embedding = embed_response.data[0].embedding

    raw = collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        where={"company": target_company.lower()},
    )

    problems: list[dict] = []
    if raw["ids"] and raw["ids"][0]:
        metas     = raw["metadatas"][0]
        distances = raw["distances"][0]
        for meta, dist in zip(metas, distances):
            problems.append({
                "title":           meta["title"],
                "slug":            meta["slug"],
                "difficulty":      meta["difficulty"],
                "tags":            meta["tags"],
                "company":         meta["company"],
                "freq_bar":        float(meta.get("freq_bar", 0.0)),
                "relevance_score": round(1 - dist, 4),
            })

    # Deduplicate by title, preserving order
    seen_titles: set[str] = set()
    unique: list[dict] = []
    for p in problems:
        if p["title"] not in seen_titles:
            seen_titles.add(p["title"])
            unique.append(p)
    problems = unique

    problems.sort(key=lambda p: p["freq_bar"], reverse=True)

    log_event(
        logger, "info", "rag_retrieval",
        company=target_company,
        query=query,
        results_count=len(problems),
        latency_ms=round((time.monotonic() - t0) * 1000),
    )

    return problems


# ---------------------------------------------------------------------------
# Prompt formatting
# ---------------------------------------------------------------------------

def format_for_prompt(problems: list[dict], n_per_week: int = 3) -> str:
    if not problems:
        return ""

    company = problems[0].get("company", "company").title() if problems else "Company"

    order = {"Easy": 0, "Medium": 1, "Hard": 2}
    problems = sorted(problems, key=lambda x: (order.get(x["difficulty"], 1), -x.get("freq_bar", 0)))

    easy_med = [p for p in problems if p["difficulty"] != "Hard"]
    hard     = [p for p in problems if p["difficulty"] == "Hard"]

    week1 = easy_med[:3]
    week2 = easy_med[3:7]
    week3 = hard[:3] if hard else easy_med[7:10]
    week4 = hard[3:] if len(hard) > 3 else hard[:3]

    def _lines(subset: list[dict]) -> str:
        if not subset:
            return "  (none available)"
        return "\n".join(
            f"  - {p['title']} [{p['difficulty']}] | {p['tags']} | freq: {p['freq_bar']:.2f}"
            for p in subset
        )

    return (
        "GROUNDED PROBLEM RECOMMENDATIONS "
        "(use ONLY these problems, do not suggest others):\n\n"
        f"Week 1 — Foundation (Easy/Medium, most frequent):\n{_lines(week1)}\n\n"
        f"Week 2 — Core Patterns (Medium):\n{_lines(week2)}\n\n"
        f"Week 3 — Advanced (Medium/Hard):\n{_lines(week3)}\n\n"
        f"Week 4 — {company}-Specific (Hardest, most asked):\n{_lines(week4)}\n\n"
        "IMPORTANT: Each week must use DIFFERENT problems. "
        "Do not repeat any problem across weeks."
    )


# ---------------------------------------------------------------------------
# Availability check
# ---------------------------------------------------------------------------

async def is_rag_available() -> bool:
    try:
        return collection.count() > 0
    except Exception as e:
        log_event(logger, "warning", "rag_availability_check_failed", error=repr(e))
        return False