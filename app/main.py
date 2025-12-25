from fastapi import FastAPI
from app.api.routes import router

app = FastAPI(
    title="LeetPulse API",
    description="LeetCode analytics and performance insights",
    version="0.1.0"
)

app.include_router(router)
