"""FastAPI application bootstrap for the data refinery service."""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config.settings import settings
from src.api.rest.historical import router as historical_router
from src.api.stream.signals import router as stream_router
from src.database.connection import init_db

logger = logging.getLogger(__name__)
logging.basicConfig(level=settings.log_level)

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


@app.on_event("startup")
async def startup_event():
    """Initialize database tables on startup."""
    try:
        logger.info("Initializing database tables...")
        await init_db()
        logger.info("Database initialization complete")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}", exc_info=True)
        # Don't crash on startup if DB is temporarily unavailable


@app.get("/")
async def root() -> dict[str, str]:
    return {"service": "b2b-saas-data-refinery", "status": "ok"}


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint that doesn't require database."""
    return {"status": "healthy", "environment": settings.environment}
