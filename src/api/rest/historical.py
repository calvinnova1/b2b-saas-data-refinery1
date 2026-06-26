"""GET /v1/signals?date_range=... — historical query API."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.authentication import require_historical
from src.database.connection import get_session
from src.database.models import Signal

router = APIRouter()


@router.get("/signals")
async def read_signals(
    tenant=Depends(require_historical),
    session: AsyncSession = Depends(get_session),
    source: Optional[str] = Query(None, description="Signal source, e.g. github"),
    signal_type: Optional[str] = Query(None, description="Signal type filter"),
    start_date: Optional[datetime] = Query(None, description="Inclusive start timestamp"),
    end_date: Optional[datetime] = Query(None, description="Inclusive end timestamp"),
    limit: int = Query(50, ge=1, le=500, description="Maximum number of signals to return"),
) -> list[dict[str, object]]:
    stmt = select(Signal).where(Signal.tenant_id == tenant.id)
    if source:
        stmt = stmt.where(Signal.source == source)
    if signal_type:
        stmt = stmt.where(Signal.signal_type == signal_type)
    if start_date:
        stmt = stmt.where(Signal.created_at >= start_date)
    if end_date:
        stmt = stmt.where(Signal.created_at <= end_date)

    stmt = stmt.order_by(Signal.created_at.desc()).limit(limit)
    result = await session.execute(stmt)
    signals = result.scalars().all()

    return [
        {
            "id": signal.id,
            "source": signal.source,
            "signal_type": signal.signal_type,
            "content": signal.content,
            "details": signal.details,
            "created_at": signal.created_at.isoformat(),
        }
        for signal in signals
    ]
