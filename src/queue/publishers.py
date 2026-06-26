"""Celery task publishers for ingestion and processing."""

from __future__ import annotations

from celery import Celery

from config.settings import settings

celery_app = Celery(
    "b2b_saas_data_refinery",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.task_serializer = "json"
celery_app.conf.result_serializer = "json"
celery_app.conf.accept_content = ["json"]
celery_app.conf.task_track_started = True


def publish_ingest_payload(payload: dict[str, object]) -> None:
    """Pushes an ingested item into the processing queue."""
    celery_app.send_task("src.queue.workers.process_signal_task", args=[payload])
