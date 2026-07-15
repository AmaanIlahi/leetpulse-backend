import json
import os
import time
from pathlib import Path
from typing import Optional

import sentry_sdk
from fastapi import HTTPException
from openai import AsyncOpenAI

from app.models.insights import InsightsResponse
from app.models.schemas import AnalyticsResponse
from app.utils.logger import get_logger, log_event

logger = get_logger(__name__)

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Load company profiles once at import time
_PROFILES_PATH = Path(__file__).resolve().parent.parent / "data" / "company_profiles.json"
with _PROFILES_PATH.open() as _f:
    _COMPANY_PROFILES: dict = json.load(_f)


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_prompt(
    analytics: AnalyticsResponse,
    target_company: Optional[str],
    rag_context: Optional[str] = None,
) -> str:
    d = analytics.difficulty
    easy   = d.get("easy",   None)
    medium = d.get("medium", None)
    hard   = d.get("hard",   None)

    easy_solved   = easy.solved   if easy   else 0
    medium_solved = medium.solved if medium else 0
    hard_solved   = hard.solved   if hard   else 0
    total_solved  = easy_solved + medium_solved + hard_solved

    hard_pct = round(hard_solved / total_solved * 100) if total_solved else 0

    diff_block = (
        f"  Easy:   {easy_solved} solved"
        + (f" / {easy.total} total"   if easy   else "") + "\n"
        f"  Medium: {medium_solved} solved"
        + (f" / {medium.total} total" if medium else "") + "\n"
        f"  Hard:   {hard_solved} solved"
        + (f" / {hard.total} total"   if hard   else "")
        + f"  ({hard_pct}% of solved problems are Hard)"
    )

    def _label(solved: int) -> str:
        if solved >= 20:
            return " (STRONG)"
        if solved <= 3:
            return " (WEAK — needs work)"
        return ""

    def _topic_lines(category: str) -> str:
        topics = sorted(
            [t for t in analytics.topics if t.category == category],
            key=lambda t: t.solved,
            reverse=True,
        )
        if not topics:
            return "  (none)"
        return "\n".join(
            f"  {t.name}: {t.solved} problems solved{_label(t.solved)}"
            for t in topics
        )

    topics_block = (
        f"ADVANCED PATTERNS (user has practiced):\n{_topic_lines('advanced')}\n\n"
        f"INTERMEDIATE TOPICS:\n{_topic_lines('intermediate')}\n\n"
        f"FUNDAMENTAL TOPICS:\n{_topic_lines('fundamental')}"
    )

    consistency = analytics.consistency
    streak_block = (
        f"  Current streak: {consistency.current_streak} days\n"
        f"  Longest streak: {consistency.longest_streak} days\n"
        f"  Active days last 30d: {consistency.active_days_30}\n"
        f"  Active days last 90d: {consistency.active_days_90}\n"
        f"  Consistency score: {consistency.consistency_score}/100"
    )

    company_block = ""
    week4_instruction = (
        "Week 4 theme must be a general advanced topic like "
        "\"Hard Problem Confidence\" or \"Contest-Level Patterns\"."
    )

    if target_company:
        profile = _COMPANY_PROFILES.get(target_company.lower())
        if profile:
            dn = profile["display_name"]
            company_block = (
                f"\nCOMPANY TARGET: {dn}\n"
                f"  Interview focus topics: {', '.join(profile['focus_topics'])}\n"
                f"  Key coding patterns they test: {', '.join(profile['focus_patterns'])}\n"
                f"  Typical difficulty mix: "
                f"{profile['difficulty_distribution']['easy']}% easy / "
                f"{profile['difficulty_distribution']['medium']}% medium / "
                f"{profile['difficulty_distribution']['hard']}% hard\n"
                f"  Style note: {profile['notes']}\n"
            )
            week4_instruction = (
                f"Week 4 theme MUST be \"{dn}-Specific Patterns\". "
                f"Its topics and patterns must come directly from {dn}'s focus list above. "
                f"Its example_problems must be well-known problems {dn} is famous for asking "
                f"(use only real Blind 75 / NeetCode 150 problems)."
            )
        else:
            logger.warning("Unknown target_company key: %r", target_company)

    rag_section = ""
    if rag_context:
        company_name = target_company or "the target company"
        rag_section = f"""

=== GROUNDED PROBLEM RECOMMENDATIONS ===
{rag_context}

CRITICAL: For example_problems in the study plan, you MUST use ONLY problems from the \
list above. Do not suggest any problem not in this list. These are real problems verified \
to be asked at {company_name}. Using problems outside this list is a hallucination."""

    example_problems_rule = (
        "- example_problems: exactly 3 problems. Use ONLY well-known problems from the "
        "Blind 75 or NeetCode 150 lists — do NOT invent problems. "
        'Append difficulty in brackets: "Word Break [Medium]", "Merge K Sorted Lists [Hard]"'
        if not rag_context else
        "- example_problems: exactly 3 problems. Choose ONLY from the GROUNDED PROBLEM "
        "RECOMMENDATIONS section above. Do not use any problem not in that list."
    )

    return f"""You are a senior software engineer and LeetCode coach writing a brutally honest, \
data-driven performance report for a specific student. Every sentence must reference \
actual numbers from the student's data. Generic advice is not acceptable.

=== PRIMARY OBJECTIVE ===
{company_block if company_block else "Give a balanced general assessment."}
You must filter EVERY recommendation through this company lens.
Strengths that are irrelevant to the target company should not be listed.
Improvements must be ranked by how critical they are for THIS company specifically, \
not by raw solved count.

=== STUDENT DATA ===

Username: {analytics.username}
Total problems solved: {total_solved}

DIFFICULTY BREAKDOWN
{diff_block}

TOPIC BREAKDOWN
{topics_block}

ACTIVITY & CONSISTENCY
{streak_block}{rag_section}

=== OUTPUT RULES ===

IMPORTANT: LeetCode uses specific tag names. Do NOT refer to generic categories like \
"Graph Theory" or "Graphs" as a single topic — they do not exist as tags. Instead \
reference the actual tags: BFS, DFS, Topological Sort, Shortest Path, Union-Find etc. \
Only cite topics that appear in the student data above with their exact names and solved \
counts. Never invent or assume a solved count — use only the numbers provided.

When referencing company focus areas, cross-reference them against the student's actual \
topic data above. If a company focuses on BFS and the student has X BFS problems solved, \
say exactly that — do not say "0 graph problems solved".

You must return a single JSON object. No markdown, no code fences, no extra keys.

--- summary ---
Write 2-3 sentences. Must cite specific numbers (e.g. "{medium_solved} mediums solved", \
"{hard_solved} hards"). Must name the single biggest gap and what closing it unlocks. \
If a company target is set, name the company and what the gap means for that interview.

--- strengths (exactly 3 items) ---
Each item must describe a PATTERN the student has demonstrated, not just a topic.
BAD: "Good at arrays"
GOOD: "Proven sliding window intuition — {easy_solved + medium_solved} easy/medium \
problems solved with strong Array and Two Pointers coverage"
Reference solved counts to justify each strength.

--- improvements (exactly 3 items) ---
Rank improvements by criticality for the target company, not by how low the solved count is.
If the company heavily tests graphs and the student has 0 graph problems, that must be \
improvement #1 regardless of other weak areas.
Each improvement must mention the company by name and explain WHY that specific gap matters \
for that company's interview style.
Each item must be specific and quantified.
BAD: "Improve graph knowledge"
GOOD: "Only {next((t.solved for t in analytics.weak_topics if 'Graph' in t.name), 0)} \
graph problems solved — Google expects fluency in BFS/DFS/Dijkstra; target 25+ problems \
in this area before interviewing"
Name exactly what to do, not just what is weak.

--- study_plan (exactly 4 weeks) ---
Week themes must be descriptive goals, NOT topic names.
BAD themes: "dynamic programming", "string", "graph theory"
GOOD themes: "Closing the Hard-Problem Gap", "Building Graph Intuition",
             "Mastering DP Patterns", "Contest-Level Optimization"

{week4_instruction}

For each week provide:
- week: integer 1-4
- theme: descriptive goal string (see above)
- topics: 2-3 specific DSA topic names to study that week
- patterns: 2-3 specific coding patterns to practice (e.g. "sliding window", \
"two-pointer on sorted array", "DP with state compression")
{example_problems_rule}

Return JSON matching exactly this shape:
{{
  "summary": "...",
  "strengths": ["...", "...", "..."],
  "improvements": ["...", "...", "..."],
  "study_plan": [
    {{
      "week": 1,
      "theme": "...",
      "topics": ["...", "..."],
      "patterns": ["...", "..."],
      "example_problems": ["Problem Name [Difficulty]", "...", "..."]
    }}
  ]
}}
"""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def generate_llm_insights(
    analytics: AnalyticsResponse,
    target_company: Optional[str] = None,
    rag_context: Optional[str] = None,
) -> InsightsResponse:
    prompt = _build_prompt(analytics, target_company, rag_context)

    log_event(
        logger, "info", "llm_call_start",
        username=analytics.username,
        target_company=target_company,
        prompt_chars=len(prompt),
    )
    t0 = time.monotonic()

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=2000,
            response_format={"type": "json_object"},
        )
    except Exception as e:
        sentry_sdk.capture_exception(e)
        log_event(
            logger, "error", "llm_call_failed",
            username=analytics.username,
            target_company=target_company,
            error=repr(e),
        )
        raise HTTPException(status_code=502, detail="LLM service unavailable")

    content = response.choices[0].message.content
    usage = response.usage

    log_event(
        logger, "info", "llm_call_complete",
        username=analytics.username,
        target_company=target_company,
        latency_ms=round((time.monotonic() - t0) * 1000),
        response_chars=len(content),
        prompt_tokens=usage.prompt_tokens if usage else None,
        completion_tokens=usage.completion_tokens if usage else None,
        total_tokens=usage.total_tokens if usage else None,
        rag_grounded=rag_context is not None,
    )

    try:
        data = json.loads(content)
    except Exception as e:
        sentry_sdk.capture_exception(e)
        log_event(
            logger, "error", "llm_parse_failed",
            username=analytics.username,
            target_company=target_company,
            raw_content=content,
            error=repr(e),
        )
        raise HTTPException(status_code=500, detail="Failed to parse LLM response")

    return InsightsResponse(
        summary=data["summary"],
        strengths=data["strengths"],
        improvements=data["improvements"],
        study_plan=data["study_plan"],
        target_company=target_company,
        rag_grounded=rag_context is not None,
    )
