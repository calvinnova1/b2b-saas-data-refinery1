"""Hacker News ingestor for the official Firebase API."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional

from src.ingestion.base_ingestor import BaseIngestor
from src.storage.redis_client import RedisRateLimitStore

logger = logging.getLogger(__name__)

HN_API_BASE_URL = "https://hacker-news.firebaseio.com/v0"


@dataclass(frozen=True)
class HackerNewsItem:
    id: int
    by: Optional[str]
    title: Optional[str]
    text: Optional[str]
    url: Optional[str]
    type: str
    time: int
    descendants: Optional[int]

    @classmethod
    def from_api_payload(cls, payload: dict[str, Any]) -> "HackerNewsItem":
        return cls(
            id=int(payload.get("id", 0)),
            by=payload.get("by"),
            title=payload.get("title"),
            text=payload.get("text"),
            url=payload.get("url"),
            type=payload.get("type", "item"),
            time=int(payload.get("time", 0)),
            descendants=payload.get("descendants"),
        )


class HackerNewsIngestor(BaseIngestor):
    def __init__(self, rate_limit_store: RedisRateLimitStore, max_retries: int = 3) -> None:
        super().__init__(
            api_name="hackernews",
            base_url=HN_API_BASE_URL,
            rate_limit_store=rate_limit_store,
            default_headers={"User-Agent": "b2b-saas-data-refinery"},
            max_retries=max_retries,
            request_timeout_seconds=30.0,
        )

    async def iter_story_ids(self, list_name: str = "new") -> AsyncIterator[int]:
        response = await self.get(f"/{list_name}stories.json")
        ids = response.json() or []
        for story_id in ids:
            yield int(story_id)

    async def get_item(self, item_id: int) -> HackerNewsItem:
        response = await self.get(f"/item/{item_id}.json")
        return HackerNewsItem.from_api_payload(response.json())

    async def iter_new_stories(self, limit: int = 50) -> AsyncIterator[HackerNewsItem]:
        count = 0
        async for item_id in self.iter_story_ids("new"):
            if count >= limit:
                break
            yield await self.get_item(item_id)
            count += 1

    def parse_rate_limit_headers(self, headers: Any) -> Optional[None]:
        return None
