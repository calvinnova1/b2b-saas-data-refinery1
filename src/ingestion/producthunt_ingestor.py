"""Product Hunt ingestor using the official GraphQL API."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional

import httpx

from src.ingestion.base_ingestor import BaseIngestor
from src.storage.redis_client import RedisRateLimitStore

logger = logging.getLogger(__name__)

PRODUCTHUNT_API_BASE_URL = "https://api.producthunt.com/v2/api"


@dataclass(frozen=True)
class ProductHuntPost:
    id: str
    name: str
    tagline: str
    url: str
    votes_count: int
    created_at: str

    @classmethod
    def from_api_payload(cls, payload: dict[str, Any]) -> "ProductHuntPost":
        node = payload.get("node", {})
        return cls(
            id=node.get("id", ""),
            name=node.get("name", ""),
            tagline=node.get("tagline", ""),
            url=node.get("redirectUrl", ""),
            votes_count=int(node.get("votesCount", 0)),
            created_at=node.get("createdAt", ""),
        )


class ProductHuntIngestor(BaseIngestor):
    def __init__(
        self,
        api_token: str,
        rate_limit_store: RedisRateLimitStore,
        max_retries: int = 3,
    ) -> None:
        super().__init__(
            api_name="producthunt",
            base_url=PRODUCTHUNT_API_BASE_URL,
            rate_limit_store=rate_limit_store,
            default_headers={
                "Authorization": f"Bearer {api_token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "b2b-saas-data-refinery",
            },
            max_retries=max_retries,
            request_timeout_seconds=30.0,
        )

    async def iter_posts(self, limit: int = 10) -> AsyncIterator[ProductHuntPost]:
        query = {
            "query": "query { posts(first: %d) { edges { node { id name tagline redirectUrl votesCount createdAt } } } }" % limit
        }
        response = await self.post("/graphql", json=query)
        data = response.json().get("data", {}).get("posts", {}).get("edges", [])
        for edge in data:
            yield ProductHuntPost.from_api_payload(edge)

    async def post(self, path: str, json: dict[str, Any]) -> httpx.Response:
        if self._client is None:
            raise RuntimeError("ProductHuntIngestor used before entering async context")
        response = await self._client.post(path, json=json)
        await self._record_rate_limit_headers(response)
        response.raise_for_status()
        return response

    def parse_rate_limit_headers(self, headers: httpx.Headers) -> Optional[None]:
        return None
