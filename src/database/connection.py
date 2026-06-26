"""Async SQLAlchemy engine/session management.

This module creates the async engine and session factory for the
application, using settings loaded from config/settings.py.
"""

from __future__ import annotations

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from config.settings import settings
from src.database.models import Base

engine: AsyncEngine = create_async_engine(
    settings.database_url,
    echo=False,
    future=True,
    pool_size=settings.database_pool_size,
)

AsyncSessionLocal = sessionmaker(
    bind=engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yields a database session for FastAPI dependencies."""
    async with AsyncSessionLocal() as session:
        yield session


async def init_db() -> None:
    """Creates database tables for all declared models."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
