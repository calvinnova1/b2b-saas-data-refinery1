"""GET /v1/stream — Server-Sent Events endpoint."""

from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator

from fastapi import APIRouter, Depends
from fastapi.responses import EventSourceResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.authentication import require_streaming
from src.database.connection import get_session
from src.database.models import Signal

router = APIRouter()


async def _signal_event_generator(session: AsyncSession) -> AsyncGenerator[str, None]:
    yield "event: connected\ndata: connected\n\n"

    stmt = select(Signal).order_by(Signal.created_at.desc()).limit(10)
    result = await session.execute(stmt)
    recent_signals = list(reversed(result.scalars().all()))

    for signal in recent_signals:
        payload = {
            "id": signal.id,
            "source": signal.source,
            "signal_type": signal.signal_type,
            "content": signal.content,
            "details": signal.details,
            "created_at": signal.created_at.isoformat(),
        }
        yield f"data: {json.dumps(payload)}\n\n"

    while True:
        yield "event: heartbeat\ndata: ping\n\n"
        await asyncio.sleep(15)


@router.get("/stream")
async def stream_signals(
    tenant=Depends(require_streaming),
    session: AsyncSession = Depends(get_session),
) -> EventSourceResponse:
    return EventSourceResponse(_signal_event_generator(session))
