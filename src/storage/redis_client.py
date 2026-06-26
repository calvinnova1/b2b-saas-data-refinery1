"""Async Redis client for distributed rate-limit state tracking.

This module provides a thin async wrapper around `redis.asyncio` whose sole
job is to let multiple ingestion workers share rate-limit state for a given
API (e.g. GitHub's per-token quota). It does NOT implement any bot-evasion
logic — it exists purely so that N concurrent workers calling the same
official API don't collectively exceed that API's documented rate limit.

Typical usage:
    redis_client = RedisRateLimitStore(redis_url="redis://localhost:6379/0")
    async with redis_client:
        await redis_client.set_remaining("github", remaining=42, reset_at=1234567890)
        remaining = await redis_client.get_remaining("github")
"""

from __future__ import annotations

import logging
from types import TracebackType
from typing import Optional

import redis.asyncio as redis

logger = logging.getLogger(__name__)


class RedisRateLimitStore:
    """Shares API rate-limit state across multiple async workers via Redis.

    Each tracked API (identified by a short string key, e.g. "github" or
    "reddit") gets two Redis keys under the hood:

    - ``ratelimit:{api_name}:remaining`` — integer, requests left in window.
    - ``ratelimit:{api_name}:reset_at`` — integer, unix timestamp when the
      window resets.

    This lets every worker process check "is it safe to make a request
    right now?" without needing its own in-memory counter, which would be
    wrong as soon as you run more than one worker.

    Attributes:
        redis_url: Connection string for the Redis instance.
        key_prefix: Prefix applied to all keys this client writes, so it can
            safely share a Redis instance with other subsystems (e.g. the
            Celery broker).
    """

    def __init__(self, redis_url: str, key_prefix: str = "ratelimit") -> None:
        """Initializes the store without opening a connection yet.

        Args:
            redis_url: A redis:// or rediss:// connection URL, e.g.
                "redis://localhost:6379/0".
            key_prefix: Namespace prefix for all keys written by this store.
        """
        self.redis_url = redis_url
        self.key_prefix = key_prefix
        self._client: Optional[redis.Redis] = None

    async def connect(self) -> None:
        """Opens the underlying Redis connection pool.

        Raises:
            redis.RedisError: If the connection cannot be established.
        """
        if self._client is not None:
            logger.debug("Redis client already connected; skipping reconnect.")
            return

        logger.info("Connecting to Redis at %s", self._redacted_url())
        self._client = redis.from_url(
            self.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
        # Fail fast if Redis is unreachable rather than discovering it on
        # the first real rate-limit check deep inside a worker loop.
        await self._client.ping()
        logger.debug("Redis connection established.")

    async def close(self) -> None:
        """Closes the Redis connection pool, if open."""
        if self._client is None:
            return
        logger.debug("Closing Redis connection.")
        await self._client.close()
        self._client = None

    async def __aenter__(self) -> "RedisRateLimitStore":
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        await self.close()

    def _redacted_url(self) -> str:
        """Returns the Redis URL with any embedded credentials masked."""
        if "@" in self.redis_url:
            scheme_and_creds, _, host_part = self.redis_url.partition("@")
            scheme = scheme_and_creds.split("://")[0]
            return f"{scheme}://***@{host_part}"
        return self.redis_url

    def _key(self, api_name: str, field: str) -> str:
        return f"{self.key_prefix}:{api_name}:{field}"

    async def set_remaining(self, api_name: str, remaining: int, reset_at: int) -> None:
        """Records the latest rate-limit snapshot for an API.

        Call this after every API response that includes rate-limit
        headers (e.g. GitHub's ``X-RateLimit-Remaining`` /
        ``X-RateLimit-Reset``), so other workers see up-to-date state.

        Args:
            api_name: Short identifier for the API, e.g. "github".
            remaining: Number of requests left in the current window.
            reset_at: Unix timestamp (seconds) when the window resets.

        Raises:
            RuntimeError: If called before `connect()`.
        """
        client = self._require_client()
        async with client.pipeline(transaction=True) as pipe:
            pipe.set(self._key(api_name, "remaining"), remaining)
            pipe.set(self._key(api_name, "reset_at"), reset_at)
            await pipe.execute()
        logger.debug(
            "Updated rate-limit state for %s: remaining=%d reset_at=%d",
            api_name,
            remaining,
            reset_at,
        )

    async def get_remaining(self, api_name: str) -> Optional[tuple[int, int]]:
        """Fetches the last known rate-limit snapshot for an API.

        Args:
            api_name: Short identifier for the API, e.g. "github".

        Returns:
            A tuple of (remaining, reset_at) if state has been recorded,
            otherwise None (e.g. on first run before any response has
            been observed).

        Raises:
            RuntimeError: If called before `connect()`.
        """
        client = self._require_client()
        remaining_raw, reset_at_raw = await client.mget(
            self._key(api_name, "remaining"),
            self._key(api_name, "reset_at"),
        )
        if remaining_raw is None or reset_at_raw is None:
            logger.debug("No rate-limit state recorded yet for %s", api_name)
            return None
        return int(remaining_raw), int(reset_at_raw)

    async def should_throttle(self, api_name: str, min_remaining: int = 1) -> bool:
        """Checks whether callers should pause before hitting this API again.

        Args:
            api_name: Short identifier for the API, e.g. "github".
            min_remaining: Treat the API as exhausted once remaining drops
                to or below this value, leaving a small safety margin.

        Returns:
            True if the known remaining-request count is at or below
            `min_remaining` AND the reset window hasn't passed yet.
            False if there's no recorded state, or the reset window has
            already elapsed (so the limit has presumably refreshed).
        """
        import time

        state = await self.get_remaining(api_name)
        if state is None:
            return False
        remaining, reset_at = state
        if time.time() >= reset_at:
            logger.debug("Rate-limit window for %s has reset.", api_name)
            return False
        if remaining <= min_remaining:
            logger.warning(
                "Throttling %s: only %d requests remaining until %d",
                api_name,
                remaining,
                reset_at,
            )
            return True
        return False

    def _require_client(self) -> redis.Redis:
        if self._client is None:
            raise RuntimeError(
                "RedisRateLimitStore used before connect(). "
                "Use 'async with RedisRateLimitStore(...)' or call connect() first."
            )
        return self._client
