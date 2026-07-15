import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.models.insights import InsightsResponse
from app.models.schemas import AnalyticsResponse
from app.utils.logger import get_logger, log_event

logger = get_logger(__name__)

_TEST_CASES_PATH = Path(__file__).resolve().parent / "test_cases.json"
_RESULTS_DIR     = Path(__file__).resolve().parent / "results"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _problem_title(entry: str) -> str:
    """Extract title from "Problem Name [Difficulty]" string."""
    return entry.split(" [")[0].strip().lower()


def _difficulty_from_entry(entry: str) -> str:
    """Extract difficulty from "Problem Name [Difficulty]" string."""
    if "[" in entry and "]" in entry:
        return entry.split("[")[-1].rstrip("]").strip().lower()
    return ""


def _rag_titles(rag_problems: list[dict]) -> set[str]:
    return {p["title"].strip().lower() for p in rag_problems}


def _rag_titles_for_company(rag_problems: list[dict], company: str) -> set[str]:
    return {
        p["title"].strip().lower()
        for p in rag_problems
        if p.get("company", "").lower() == company.lower()
    }


def _skill_level(total_solved: int) -> str:
    if total_solved < 100:
        return "beginner"
    if total_solved < 300:
        return "intermediate"
    if total_solved < 600:
        return "advanced"
    return "expert"


def _expected_difficulties(skill: str) -> set[str]:
    if skill == "beginner":
        return {"easy", "medium"}
    if skill == "intermediate":
        return {"medium"}
    return {"medium", "hard"}


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

async def score_insights(
    insights: InsightsResponse,
    analytics: AnalyticsResponse,
    target_company: str,
    rag_problems: list[dict],
) -> dict:
    all_example_entries: list[str] = []
    all_topics_patterns: list[str] = []

    for week in insights.study_plan:
        all_example_entries.extend(week.example_problems)
        all_topics_patterns.extend(week.topics)
        all_topics_patterns.extend(week.patterns)

    total_examples = len(all_example_entries)

    # --- a. Grounding score ---
    rag_all = _rag_titles(rag_problems)
    grounding = (
        sum(1 for e in all_example_entries if _problem_title(e) in rag_all) / total_examples
        if total_examples and insights.rag_grounded
        else 1.0  # not grounded — treat as N/A, don't penalise
    )

    # --- b. Company relevance ---
    rag_company = _rag_titles_for_company(rag_problems, target_company)
    company_relevance = (
        sum(1 for e in all_example_entries if _problem_title(e) in rag_company) / total_examples
        if total_examples and rag_company
        else 0.0
    )

    # --- c. Pattern coverage ---
    weak_names = {t.name.lower() for t in analytics.weak_topics[:5]}
    plan_terms = {s.lower() for s in all_topics_patterns}
    pattern_coverage = (
        len(weak_names & plan_terms) / len(weak_names)
        if weak_names
        else 1.0
    )

    # --- d. Difficulty fit ---
    total_solved = sum(d.solved for d in analytics.difficulty.values())
    skill = _skill_level(total_solved)
    expected = _expected_difficulties(skill)
    difficulty_fit = (
        sum(1 for e in all_example_entries if _difficulty_from_entry(e) in expected) / total_examples
        if total_examples
        else 1.0
    )

    scores = {
        "grounding":          round(grounding, 3),
        "company_relevance":  round(company_relevance, 3),
        "pattern_coverage":   round(pattern_coverage, 3),
        "difficulty_fit":     round(difficulty_fit, 3),
        "rag_grounded":       insights.rag_grounded,
    }
    scores["overall"] = round(
        (scores["grounding"] + scores["company_relevance"]
         + scores["pattern_coverage"] + scores["difficulty_fit"]) / 4,
        3,
    )
    return scores


# ---------------------------------------------------------------------------
# Eval runner
# ---------------------------------------------------------------------------

async def run_evals() -> dict:
    from app.services.leetcode import fetch_all
    from app.services.analytics import compute_analytics
    from app.services.rag.retriever import retrieve_problems, format_for_prompt, is_rag_available
    from app.services.llm import generate_llm_insights

    test_cases = json.loads(_TEST_CASES_PATH.read_text())["test_cases"]

    rag_ready = await is_rag_available()

    by_company: dict[str, list[dict]] = {}
    by_skill:   dict[str, list[dict]] = {}

    for case in test_cases:
        username    = case["username"]
        skill_level = case["skill_level"]
        companies   = case["companies"]

        try:
            raw       = await fetch_all(username)
            analytics = compute_analytics(raw)
        except Exception as e:
            log_event(logger, "warning", "eval_fetch_failed", username=username, error=repr(e))
            continue

        total_solved = sum(d.solved for d in analytics.difficulty.values())
        if total_solved < 100:
            difficulty_focus = "easy medium"
        elif total_solved < 400:
            difficulty_focus = "medium"
        else:
            difficulty_focus = "medium hard"

        for company in companies:
            rag_problems: list[dict] = []
            rag_context: Optional[str] = None

            if rag_ready:
                try:
                    weak_topic_names = [t.name for t in analytics.weak_topics]
                    rag_problems = await retrieve_problems(
                        weak_topics=weak_topic_names,
                        target_company=company,
                        difficulty_focus=difficulty_focus,
                        n_results=15,
                    )
                    if rag_problems:
                        rag_context = format_for_prompt(rag_problems, n_per_week=3)
                except Exception as e:
                    log_event(logger, "warning", "eval_rag_failed",
                              username=username, company=company, error=repr(e))

            try:
                insights = await generate_llm_insights(analytics, company, rag_context)
            except Exception as e:
                log_event(logger, "warning", "eval_llm_failed",
                          username=username, company=company, error=repr(e))
                continue

            scores = await score_insights(insights, analytics, company, rag_problems)

            key = company.lower()
            by_company.setdefault(key, []).append(scores)
            by_skill.setdefault(skill_level, []).append(scores)

    def _avg(score_list: list[dict]) -> dict:
        if not score_list:
            return {}
        keys = ["grounding", "company_relevance", "pattern_coverage", "difficulty_fit", "overall"]
        return {k: round(sum(s[k] for s in score_list) / len(score_list), 3) for k in keys}

    by_company_avg  = {c: _avg(v) for c, v in by_company.items()}
    by_skill_avg    = {s: _avg(v) for s, v in by_skill.items()}

    all_scores = [s for lst in by_company.values() for s in lst]
    overall_score = round(
        sum(s["overall"] for s in all_scores) / len(all_scores), 3
    ) if all_scores else 0.0

    results = {
        "date":           datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "overall_score":  overall_score,
        "by_company":     by_company_avg,
        "by_skill_level": by_skill_avg,
    }

    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    date_str  = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    out_path  = _RESULTS_DIR / f"{date_str}.json"
    out_path.write_text(json.dumps(results, indent=2))

    log_event(
        logger, "info", "eval_complete",
        overall_score=overall_score,
        by_company={c: v.get("overall") for c, v in by_company_avg.items()},
        result_file=str(out_path),
    )

    if overall_score < 0.7:
        log_event(logger, "warning", "eval_warning",
                  message="RAG quality below threshold",
                  overall_score=overall_score)

    return results
