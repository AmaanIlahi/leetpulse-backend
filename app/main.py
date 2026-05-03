import os
from contextlib import asynccontextmanager
from dotenv import load_dotenv
load_dotenv()

import posthog
posthog.api_key = os.getenv("POSTHOG_API_KEY")
posthog.host = "https://us.i.posthog.com"
posthog.disabled = not os.getenv("POSTHOG_API_KEY")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    if os.getenv("POSTHOG_API_KEY"):
        posthog.flush()


app = FastAPI(
    title="LeetPulse API",
    description="LeetCode analytics and performance insights",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware (REQUIRED for frontend)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # MVP: allow all (tighten later)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
