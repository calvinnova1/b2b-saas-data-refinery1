"""Celery worker tasks for processing and persisting signals."""

from __future__ import annotations

import json

from celery import Celery
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from src.database.connection import AsyncSessionLocal, engine
from src.database.models import Signal
from src.processing.dual_sentiment import DualSentimentAnalyzer
from src.processing.intent_classifier import IntentClassifier
from src.processing.switch_extractor import SwitchExtractor
from src.processing.validity_checker import ValidityChecker

celery_app = Celery(
    "b2b_saas_data_refinery",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.task_serializer = "json"
celery_app.conf.result_serializer = "json"
celery_app.conf.accept_content = ["json"]
celery_app.conf.task_track_started = True


def _create_signal_payload(raw_payload: dict[str, object]) -> dict[str, object]:
    content = raw_payload.get("content", "")
    intent = IntentClassifier().predict_intent(content)
    switch = SwitchExtractor().extract_switches(content)
    sentiment = DualSentimentAnalyzer().analyze(content)
    valid = ValidityChecker().is_valid(content)

    return {
        "source": raw_payload.get("source", "unknown"),
        "signal_type": raw_payload.get("signal_type", "generic"),
        "content": content,
        "metadata": {
            "intent": intent,
            "switches": switch,
            "sentiment": sentiment,
            "valid": valid,
            **{k: v for k, v in raw_payload.items() if k not in {"source", "signal_type", "content"}},
        },
    }


import asyncio

@celery_app.task(name="src.queue.workers.process_signal_task")
def process_signal_task(raw_payload: dict[str, object]) -> dict[str, object]:
    """Processes an ingested payload and persists it to the database."""
    payload = _create_signal_payload(raw_payload)

    async def _persist() -> dict[str, object]:
        async with AsyncSessionLocal() as session:
            signal = Signal(
                tenant_id=int(raw_payload.get("tenant_id", 1)),
                source=payload["source"],
                signal_type=payload["signal_type"],
                content=payload["content"],
                details=payload["metadata"],
            )
            session.add(signal)
            await session.commit()
            await session.refresh(signal)
            return {"id": signal.id, "status": "saved"}

    try:
        result = asyncio.run(_persist())
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(_persist())
        finally:
            loop.close()
    return result
