# LeetPulse — Backend

FastAPI service that fetches LeetCode data, computes analytics, and generates AI coaching via GPT-4o-mini.

## Architecture

```
Client
  │
  ▼
Next.js Frontend  ──────────────────────────────────────────────────────────┐
                                                                             │
                  ┌──────────────────────────────────────────────────────────▼──┐
                  │                  FastAPI Backend                              │
                  │                                                               │
                  │   GET /analyze/{username}        POST /insights/{username}    │
                  │          │                                │                   │
                  │          ▼                                ▼                   │
                  │   fetch_all() ──── asyncio.gather ────────┘                  │
                  │          │           (8 endpoints in parallel)                │
                  │          ▼                                                    │
                  │   alfa-leetcode-api.onrender.com                              │
                  │    /profile  /solved  /skill  /language                       │
                  │    /acSubmission  /calendar  /contest  /progress              │
                  │          │                                                    │
                  │          ▼                                                    │
                  │   compute_analytics()  →  AnalyticsResponse                  │
                  │          │                                                    │
                  │          ▼                                                    │
                  │   generate_llm_insights()  →  GPT-4o-mini                    │
                  │          │                                                    │
                  │          ▼                                                    │
                  │   InsightsResponse  (24h in-memory cache)                    │
                  └──────────────────────────────────────────────────────────────┘
```

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | Yes | OpenAI API key for GPT-4o-mini insights |

Copy `.env.example` to `.env` and fill in your key:

```bash
cp .env.example .env
```

## Local Setup

**Requirements:** Python 3.9+

```bash
# 1. Create and activate a virtual environment
python -m venv venv
source venv/bin/activate        # macOS/Linux
venv\Scripts\activate           # Windows

# 2. Install dependencies
pip install -r requirements.txt

# 3. Add environment variables
cp .env.example .env
# edit .env and set OPENAI_API_KEY

# 4. Start the dev server
uvicorn app.main:app --reload
```

The API will be available at `http://localhost:8000`.
Interactive docs at `http://localhost:8000/docs`.

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness check |
| `GET` | `/analyze/{username}` | Full analytics for a LeetCode user |
| `POST` | `/insights/{username}` | AI coaching; body: `{ "target_company": "google" \| null }` |

### Company keys accepted by `/insights`

`meta` · `google` · `amazon` · `microsoft` · `apple` · `netflix` · `uber` · `bloomberg`

## Project Structure

```
app/
├── api/
│   └── routes.py          # FastAPI router — /health, /analyze, /insights
├── data/
│   └── company_profiles.json  # DSA focus areas per company
├── models/
│   ├── schemas.py         # AnalyticsResponse and all sub-models
│   └── insights.py        # InsightsResponse, WeekPlan
├── services/
│   ├── analytics.py       # Transforms raw API data → AnalyticsResponse
│   ├── cache.py           # In-memory TTL cache (24h)
│   ├── leetcode.py        # Parallel fetch of 8 LeetCode endpoints
│   └── llm.py             # GPT-4o-mini prompt builder + caller
├── utils/                 # (reserved)
└── main.py                # App factory, CORS
```

## Deployment — Fly.io

```bash
# Install flyctl: https://fly.io/docs/hands-on/install-flyctl/
fly launch          # creates fly.toml, detects Python app
fly secrets set OPENAI_API_KEY=sk-...
fly deploy
```

Set `NEXT_PUBLIC_API_BASE_URL` in the frontend to your Fly.io app URL
(e.g. `https://leetpulse-backend.fly.dev`).
