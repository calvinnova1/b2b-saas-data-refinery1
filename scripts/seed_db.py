"""Initial tenant setup script for development and testing."""

from __future__ import annotations

import asyncio

from config.settings import settings
from src.database.connection import engine
from src.database.models import Base, Subscription, Tenant


async def seed() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with engine.begin() as conn:
        result = await conn.execute(
            Tenant.__table__.select().where(Tenant.name == "default")
        )
        tenant = result.scalar_one_or_none()
        if tenant is None:
            insert_result = await conn.execute(
                Tenant.__table__.insert().values(
                    name="default",
                    api_key=settings.api_secret_key or "dev-local-api-key",
                    plan="free",
                )
            )
            tenant_id = insert_result.inserted_primary_key[0]
        else:
            tenant_id = tenant.id

        existing_sub = await conn.execute(
            Subscription.__table__.select().where(Subscription.tenant_id == tenant_id)
        )
        if existing_sub.scalar_one_or_none() is None:
            await conn.execute(
                Subscription.__table__.insert().values(
                    tenant_id=tenant_id,
                    tier="free",
                    enabled_features={"stream": True, "historical": True},
                )
            )

    print("Seeded default tenant and subscription.")


if __name__ == "__main__":
    asyncio.run(seed())
