# 🧠 LeetPulse Backend

LeetPulse is an **AI-powered LeetCode analytics backend** that combines deterministic performance analysis with LLM-generated coaching insights.  
It exposes a FastAPI-based REST API that powers a React + TypeScript dashboard.

---

## 🚀 Features

- 📊 **LeetCode Performance Analytics**
  - Difficulty-wise progress (Easy / Medium / Hard)
  - Topic-wise problem distribution
  - Percentile-based performance insights

- 🤖 **AI-Powered Coaching Insights**
  - Strengths & weaknesses analysis
  - Focus topic recommendations
  - Personalized short-term study plan
  - Generated using GPT-4o-mini

- ⚡ **Production-Ready Architecture**
  - FastAPI with async endpoints
  - External API ingestion
  - In-memory caching for LLM responses
  - Graceful fallback when AI is unavailable

---

## 🏗️ Tech Stack

- **Backend Framework:** FastAPI (Python)
- **LLM:** OpenAI GPT-4o-mini
- **HTTP Client:** httpx
- **Data Validation:** Pydantic
- **Deployment:** Render
- **Runtime:** Python 3.9.18

---

## 📁 Project Structure

```text
leetpulse-backend/
├── app/
│   ├── api/
│   │   └── routes.py          # API endpoints
│   ├── services/
│   │   ├── leetcode.py        # LeetCode API ingestion
│   │   ├── analytics.py       # Deterministic analytics logic
│   │   ├── llm.py             # GPT-powered insight generation
│   │   ├── cache.py           # In-memory caching (TTL-based)
│   │   └── analyze.py         # Shared analysis service
│   ├── models/
│   │   ├── schemas.py         # Analyze endpoint schema
│   │   └── insights.py        # AI insights schema
│   └── main.py                # FastAPI app entry point
├── requirements.txt
├── runtime.txt
└── README.md
