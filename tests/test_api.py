"""Integration tests for the FastAPI API endpoints."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient
from sqlalchemy import select

from config.settings import settings
from src.api.main import app
from src.database.connection import engine
from src.database.models import Base, Signal, Subscription, Tenant


def setup_module(module) -> None:
    async def init_db() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with engine.begin() as conn:
            result = await conn.execute(
                select(Tenant.id).where(Tenant.name == "default")
            )
            tenant_id = result.scalar_one_or_none()
            if tenant_id is None:
                insert_result = await conn.execute(
                    Tenant.__table__.insert().values(
                        name="default",
                        api_key=settings.api_secret_key or "dev-local-api-key",
                        plan="free",
                    )
                )
                tenant_id = insert_result.inserted_primary_key[0]

            result = await conn.execute(
                select(Subscription.id).where(Subscription.tenant_id == tenant_id)
            )
            if result.scalar_one_or_none() is None:
                await conn.execute(
                    Subscription.__table__.insert().values(
                        tenant_id=tenant_id,
                        tier="free",
                        enabled_features={"stream": True, "historical": True},
                    )
                )

            result = await conn.execute(
                select(Signal).where(Signal.tenant_id == tenant_id)
            )
            if result.scalar_one_or_none() is None:
                await conn.execute(
                    Signal.__table__.insert().values(
                        tenant_id=tenant_id,
                        source="test",
                        signal_type="note",
                        content="sample content",
                        details={"foo": "bar"},
                    )
                )

    asyncio.run(init_db())


client = TestClient(app)


def test_root() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"service": "b2b-saas-data-refinery", "status": "ok"}


def test_historical_signals_authorized() -> None:
    response = client.get(
        "/v1/signals",
        headers={"Authorization": f"Bearer {settings.api_secret_key}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert any(signal.get("source") == "test" for signal in data)


def test_stream_signals_authorized() -> None:
    with client.stream(
        "GET",
        "/v1/stream",
        headers={"Authorization": f"Bearer {settings.api_secret_key}"},
    ) as response:
        assert response.status_code == 200
        text = ""
        for chunk in response.iter_text():
            if chunk:
                text += chunk
            if "event: connected" in text:
                break

    assert "event: connected" in text
    assert "data: connected" in text
