import json
import os
from typing import Dict
from openai import AsyncOpenAI

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


async def generate_llm_insights(analysis_data: Dict) -> Dict:
    """
    Generates structured insights using GPT-4o-mini.
    Guaranteed JSON output.
    """

    prompt = f"""
    You are an expert LeetCode mentor.

    Analyze the following performance data and return ONLY valid JSON.
    Do not include markdown, explanations, or extra text.

    The JSON MUST contain exactly these keys:
    - summary
    - strengths (array of strings)
    - weaknesses (array of strings)
    - focus_topics (array of {{topic, reason}})
    - study_plan (array of {{day, task}})

    Guidelines:
    - Frame weaknesses relative to the user's own strengths, not absolute failure
    - Limit focus_topics to the top 3–4 highest impact areas
    - Use "Day 1", "Day 2", etc. for study_plan.day
    - Keep insights concise, actionable, and encouraging

    Performance data:
    {json.dumps(analysis_data, indent=2)}
    """

    try:
        response = await client.responses.create(
            model="gpt-4o-mini",
            input=prompt,
            temperature=0.3,
            max_output_tokens=700,
        )

        # Correct way to extract text from Responses API
        content = response.output_text
        print("\n--- LLM RAW RESPONSE ---\n", content, "\n-----------------------\n")

        # Safe JSON extraction
        start = content.find("{")
        end = content.rfind("}") + 1
        json_text = content[start:end]

        return json.loads(json_text)

    except Exception as e:
        print("\n--- LLM ERROR ---\n", repr(e), "\n----------------\n")
        raise
