"""Reddit ingestor using the official public Reddit API."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional

import httpx

from src.ingestion.base_ingestor import BaseIngestor, RateLimitInfo
from src.storage.redis_client import RedisRateLimitStore

logger = logging.getLogger(__name__)

REDDIT_API_BASE_URL = "https://oauth.reddit.com"
REDDIT_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"


@dataclass(frozen=True)
class RedditPost:
    id: str
    title: str
    selftext: str
    author: Optional[str]
    subreddit: str
    score: int
    num_comments: int
    created_utc: float
    url: str

    @classmethod
    def from_api_payload(cls, payload: dict[str, Any]) -> "RedditPost":
        data = payload.get("data", {})
        return cls(
            id=data.get("id", ""),
            title=data.get("title", ""),
            selftext=data.get("selftext", ""),
            author=data.get("author"),
            subreddit=data.get("subreddit", ""),
            score=int(data.get("score", 0)),
            num_comments=int(data.get("num_comments", 0)),
            created_utc=float(data.get("created_utc", 0.0)),
            url=data.get("url", ""),
        )


@dataclass(frozen=True)
class RedditComment:
    id: str
    body: str
    author: Optional[str]
    created_utc: float

    @classmethod
    def from_api_payload(cls, payload: dict[str, Any]) -> "RedditComment":
        data = payload.get("data", {})
        return cls(
            id=data.get("id", ""),
            body=data.get("body", ""),
            author=data.get("author"),
            created_utc=float(data.get("created_utc", 0.0)),
        )


class RedditIngestor(BaseIngestor):
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        user_agent: str,
        rate_limit_store: RedisRateLimitStore,
        max_retries: int = 3,
        request_timeout_seconds: float = 30.0,
    ) -> None:
        super().__init__(
            api_name="reddit",
            base_url=REDDIT_API_BASE_URL,
            rate_limit_store=rate_limit_store,
            default_headers={"User-Agent": user_agent},
            max_retries=max_retries,
            request_timeout_seconds=request_timeout_seconds,
        )
        self.client_id = client_id
        self.client_secret = client_secret
        self.user_agent = user_agent
        self._access_token: Optional[str] = None

    async def __aenter__(self) -> "RedditIngestor":
        await super().__aenter__()
        await self._refresh_token()
        return self

    async def _refresh_token(self) -> None:
        async with httpx.AsyncClient(timeout=self.request_timeout_seconds) as auth_client:
            response = await auth_client.post(
                REDDIT_TOKEN_URL,
                auth=(self.client_id, self.client_secret),
                data={"grant_type": "client_credentials"},
                headers={"User-Agent": self.user_agent},
            )
            response.raise_for_status()
            payload = response.json()
            token = payload.get("access_token")
            if not token:
                raise RuntimeError("Failed to obtain Reddit access token")
            self._access_token = token
            if self._client is not None:
                self._client.headers["Authorization"] = f"Bearer {token}"

    async def iter_subreddit_posts(
        self,
        subreddit: str,
        sort: str = "new",
        limit: int = 25,
    ) -> AsyncIterator[RedditPost]:
        response = await self.get(f"/r/{subreddit}/{sort}", params={"limit": limit})
        listing = response.json()
        for child in listing.get("data", {}).get("children", []):
            yield RedditPost.from_api_payload(child)

    async def get_comments(self, post_id: str) -> list[RedditComment]:
        response = await self.get(f"/comments/{post_id}", params={"limit": 100})
        comments: list[RedditComment] = []
        for item in response.json():
            data = item.get("data", {})
            for child in data.get("children", []):
                if child.get("kind") == "t1":
                    comments.append(RedditComment.from_api_payload(child))
        return comments

    def parse_rate_limit_headers(self, headers: httpx.Headers) -> Optional[RateLimitInfo]:
        remaining = headers.get("x-ratelimit-remaining")
        reset = headers.get("x-ratelimit-reset")
        if remaining is None or reset is None:
            return None
        try:
            return RateLimitInfo(remaining=int(float(remaining)), reset_at=int(time.time() + float(reset)))
        except ValueError:
            return None
