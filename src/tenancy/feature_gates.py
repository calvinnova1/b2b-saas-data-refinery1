"""Tenant feature gate resolution and API key lookup."""

from __future__ import annotations

from dataclasses import dataclass

from config.settings import settings


@dataclass(frozen=True)
class Tenant:
    id: int
    name: str
    plan: str
    features: dict[str, bool]


def get_feature_gates_for_plan(plan: str) -> dict[str, bool]:
    if plan == "enterprise":
        return {
            "stream": True,
            "historical": True,
            "dual_sentiment": True,
            "switch_extraction": True,
        }
    if plan == "pro":
        return {
            "stream": True,
            "historical": True,
            "dual_sentiment": True,
            "switch_extraction": False,
        }
    return {"stream": True, "historical": True, "dual_sentiment": False, "switch_extraction": False}


def resolve_api_key(api_key: str) -> Tenant:
    if not settings.api_secret_key:
        raise ValueError("API key validation is not configured.")

    if api_key != settings.api_secret_key:
        raise ValueError("Invalid API key.")

    return Tenant(
        id=1,
        name="default",
        plan="free",
        features=get_feature_gates_for_plan("free"),
    )
