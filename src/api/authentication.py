"""API key validation and tenant feature gating for FastAPI."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from config.settings import settings
from src.tenancy.feature_gates import Tenant, resolve_api_key

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_tenant(
    credentials: HTTPAuthorizationCredentials = Security(bearer_scheme),
) -> Tenant:
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authorization credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    api_key = credentials.credentials
    try:
        return resolve_api_key(api_key)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc) or "Invalid API key.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def authorize_feature(feature_name: str, tenant: Tenant) -> Tenant:
    if not tenant.features.get(feature_name, False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Tenant plan {tenant.plan} does not allow feature '{feature_name}'",
        )
    return tenant


def require_streaming(tenant: Tenant = Depends(get_current_tenant)) -> Tenant:
    return authorize_feature("stream", tenant)


def require_historical(tenant: Tenant = Depends(get_current_tenant)) -> Tenant:
    return authorize_feature("historical", tenant)
