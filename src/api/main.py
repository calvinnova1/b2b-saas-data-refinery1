"""FastAPI application bootstrap for the data refinery service."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config.settings import settings
from src.api.rest.historical import router as historical_router
from src.api.stream.signals import router as stream_router

app = FastAPI(
    title="B2B SaaS Data Refinery",
    description="Enriched B2B software feedback streaming and historical query API.",
    debug=settings.environment != "production",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(historical_router, prefix="/v1")
app.include_router(stream_router, prefix="/v1")


@app.get("/")
async def root() -> dict[str, str]:
    return {"service": "b2b-saas-data-refinery", "status": "ok"}
