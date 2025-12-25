from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import router

app = FastAPI(
    title="LeetPulse API",
    description="LeetCode analytics and performance insights",
    version="0.1.0"
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
