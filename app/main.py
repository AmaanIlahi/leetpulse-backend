import os
from contextlib import asynccontextmanager
from dotenv import load_dotenv
load_dotenv()

from app.utils.logger import setup_logging, get_logger, log_event
setup_logging()

logger = get_logger(__name__)

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.asyncio import AsyncioIntegration

if os.getenv("SENTRY_DSN"):
    sentry_sdk.init(
        dsn=os.getenv("SENTRY_DSN"),
        integrations=[FastApiIntegration(), AsyncioIntegration()],
        traces_sample_rate=0.2,
        environment="production" if os.getenv("FLY_APP_NAME") else "development",
    )

import posthog
posthog.api_key = os.getenv("POSTHOG_API_KEY")
posthog.host = "https://us.i.posthog.com"
posthog.disabled = not os.getenv("POSTHOG_API_KEY")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.api.routes import router
from app.services.rag.scheduler import start_scheduler, shutdown_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler(app)
    yield
    shutdown_scheduler()
    if os.getenv("POSTHOG_API_KEY"):
        posthog.flush()


app = FastAPI(
    title="LeetPulse API",
    description="LeetCode analytics and performance insights",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # MVP: allow all (tighten later)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    log_event(
        logger, "error", "unhandled_exception",
        path=str(request.url),
        error=str(exc),
    )
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
