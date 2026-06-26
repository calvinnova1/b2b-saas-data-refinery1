"""Async base class for ingesting data from official, rate-limited APIs.

This module is the shared foundation for every source-specific ingestor
(GitHub, Reddit, Hacker News, Product Hunt, etc). It is intentionally
narrow in scope: it knows how to make an HTTP request, read that API's
rate-limit headers, back off when the API tells it to, and retry on
transient server errors. It has no knowledge of any anti-bot evasion
technique (no proxy rotation, no user-agent spoofing, no stealth
configuration) because none of that is appropriate when calling an API
you are permitted to use.

Subclasses are responsible for:
    - Knowing the base URL and auth scheme for their API.
    - Parsing that API's specific rate-limit header names into the
      generic (remaining, reset_at) tuple this base class expects.
    - Turning raw JSON responses into domain objects.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
import uuid
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Optional

import httpx

from src.storage.redis_client import RedisRateLimitStore

logger = logging.getLogger(__name__)


class RateLimitExceededError(Exception):
    """Raised when an API's rate limit is exhausted and retries are exhausted too."""


class IngestorHTTPError(Exception):
    """Raised when an API request fails after exhausting all retries."""


@dataclass(frozen=True)
class RateLimitInfo:
    """Generic, API-agnostic view of a rate-limit snapshot.

    Attributes:
        remaining: Number of requests left in the current window.
        reset_at: Unix timestamp (seconds) when the window resets.
    """

    remaining: int
    reset_at: int


class BaseIngestor:
    """Async base class for fetching data from a single official API.

    Handles the cross-cutting concerns every API client needs: a shared
    `httpx.AsyncClient`, structured logging with request IDs, exponential
    backoff with jitter on transient failures (429/5xx), and rate-limit
    bookkeeping shared across workers via Redis. Subclasses implement the
    API-specific parts.

    Attributes:
        api_name: Short identifier used as the Redis namespace and in logs,
            e.g. "github".
        base_url: Root URL all requests are made relative to.
        rate_limit_store: Shared rate-limit tracker. Pass the same instance
            (backed by the same Redis) to every worker so they coordinate.
        max_retries: Maximum retry attempts for transient failures.
        request_timeout_seconds: Per-request timeout.
    """

    def __init__(
        self,
        api_name: str,
        base_url: str,
        rate_limit_store: RedisRateLimitStore,
        default_headers: Optional[dict[str, str]] = None,
        max_retries: int = 3,
        request_timeout_seconds: float = 30.0,
    ) -> None:
        """Initializes the ingestor.

        Args:
            api_name: Short identifier for this API, e.g. "github". Used to
                namespace rate-limit state in Redis and in log lines.
            base_url: Root URL for the API, e.g. "https://api.github.com".
            rate_limit_store: A connected (or connectable) RedisRateLimitStore
                shared across all workers calling this API.
            default_headers: Headers sent on every request — typically auth
                (e.g. "Authorization": "Bearer <token>") and an honest,
                identifying User-Agent / contact string, per the API's own
                guidelines. This is the opposite of UA rotation: APIs
                generally ask that you identify your application clearly.
            max_retries: Max retry attempts for 429/5xx responses.
            request_timeout_seconds: Timeout applied to each HTTP request.
        """
        self.api_name = api_name
        self.base_url = base_url.rstrip("/")
        self.rate_limit_store = rate_limit_store
        self.default_headers = default_headers or {}
        self.max_retries = max_retries
        self.request_timeout_seconds = request_timeout_seconds
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "BaseIngestor":
        """Opens the underlying HTTP client and ensures Redis is connected."""
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=self.default_headers,
            timeout=self.request_timeout_seconds,
        )
        # Idempotent: if the caller already connected the shared store,
        # this is a no-op.
        await self.rate_limit_store.connect()
        logger.debug("Opened HTTP client for %s (%s)", self.api_name, self.base_url)
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        """Closes the underlying HTTP client.

        Note: deliberately does not close `rate_limit_store` here, since it
        may be shared by other ingestors/workers with their own lifecycle.
        """
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            logger.debug("Closed HTTP client for %s", self.api_name)

    async def get(
        self,
        path: str,
        params: Optional[dict[str, Any]] = None,
        min_remaining_buffer: int = 1,
    ) -> httpx.Response:
        """Performs a rate-limit-aware GET request with retry on failure.

        Before issuing the request, checks Redis to see whether this API's
        quota (as last observed by *any* worker) is nearly exhausted; if so,
        sleeps until the window resets rather than firing a request that's
        likely to be rejected anyway. After every response, updates Redis
        with the freshest rate-limit snapshot so other workers benefit.

        Args:
            path: Path relative to `base_url`, e.g. "/repos/owner/repo/issues".
            params: Optional query parameters.
            min_remaining_buffer: Safety margin — pause proactively once
                remaining requests drop to or below this number.

        Returns:
            The successful `httpx.Response`.

        Raises:
            RateLimitExceededError: If the API's quota is exhausted and
                waiting for the reset isn't feasible (e.g. reset is absurdly
                far in the future, which usually indicates a config issue).
            IngestorHTTPError: If the request fails after exhausting retries.
        """
        request_id = str(uuid.uuid4())
        client = self._require_client()

        await self._wait_if_throttled(request_id, min_remaining_buffer)

        attempt = 0
        last_exc: Optional[BaseException] = None

        while attempt <= self.max_retries:
            log_ctx = {"request_id": request_id, "api": self.api_name, "path": path}
            try:
                logger.debug("Requesting %s%s [%s]", self.base_url, path, log_ctx)
                response = await client.get(path, params=params)
                await self._record_rate_limit_headers(response)

                if response.status_code == 429:
                    retry_after = self._parse_retry_after(response)
                    logger.warning(
                        "429 from %s on attempt %d/%d [%s]; backing off %.1fs",
                        self.api_name,
                        attempt + 1,
                        self.max_retries,
                        log_ctx,
                        retry_after,
                    )
                    await asyncio.sleep(retry_after)
                    attempt += 1
                    continue

                if 500 <= response.status_code < 600:
                    backoff = self._compute_backoff(attempt)
                    logger.warning(
                        "Server error %d from %s on attempt %d/%d [%s]; "
                        "retrying in %.1fs",
                        response.status_code,
                        self.api_name,
                        attempt + 1,
                        self.max_retries,
                        log_ctx,
                        backoff,
                    )
                    await asyncio.sleep(backoff)
                    attempt += 1
                    continue

                response.raise_for_status()
                logger.info(
                    "Fetched %s%s successfully (status=%d) [%s]",
                    self.base_url,
                    path,
                    response.status_code,
                    log_ctx,
                )
                return response

            except httpx.TimeoutException as exc:
                last_exc = exc
                backoff = self._compute_backoff(attempt)
                logger.warning(
                    "Timeout calling %s on attempt %d/%d [%s]; retrying in %.1fs",
                    self.api_name,
                    attempt + 1,
                    self.max_retries,
                    log_ctx,
                    backoff,
                )
                await asyncio.sleep(backoff)
                attempt += 1

            except httpx.HTTPStatusError as exc:
                # Non-retryable client error (e.g. 401, 404). Don't burn
                # retries on something that won't change.
                logger.error(
                    "Non-retryable HTTP error from %s: %s [%s]",
                    self.api_name,
                    exc,
                    log_ctx,
                )
                raise IngestorHTTPError(str(exc)) from exc

            except httpx.HTTPError as exc:
                last_exc = exc
                backoff = self._compute_backoff(attempt)
                logger.warning(
                    "Transport error calling %s on attempt %d/%d [%s]: %s; "
                    "retrying in %.1fs",
                    self.api_name,
                    attempt + 1,
                    self.max_retries,
                    log_ctx,
                    exc,
                    backoff,
                )
                await asyncio.sleep(backoff)
                attempt += 1

        logger.error(
            "Exhausted %d retries calling %s%s [request_id=%s]",
            self.max_retries,
            self.base_url,
            path,
            request_id,
        )
        raise IngestorHTTPError(
            f"Failed to fetch {path} from {self.api_name} after "
            f"{self.max_retries} retries"
        ) from last_exc

    async def _wait_if_throttled(self, request_id: str, min_remaining_buffer: int) -> None:
        """Sleeps until the rate-limit window resets if quota is nearly gone.

        Args:
            request_id: Correlation ID for log lines.
            min_remaining_buffer: Safety margin before treating quota as
                exhausted.

        Raises:
            RateLimitExceededError: If the wait would be unreasonably long
                (over 1 hour), which likely indicates misconfigured state
                rather than a real short-lived window.
        """
        if not await self.rate_limit_store.should_throttle(
            self.api_name, min_remaining=min_remaining_buffer
        ):
            return

        state = await self.rate_limit_store.get_remaining(self.api_name)
        if state is None:
            return
        _, reset_at = state
        wait_seconds = max(0.0, reset_at - time.time())

        if wait_seconds > 3600:
            raise RateLimitExceededError(
                f"{self.api_name} rate limit reset is {wait_seconds:.0f}s away; "
                "refusing to block this long. Check stored rate-limit state."
            )

        logger.info(
            "Proactively pausing %.1fs for %s rate-limit window to reset "
            "[request_id=%s]",
            wait_seconds,
            self.api_name,
            request_id,
        )
        await asyncio.sleep(wait_seconds)

    async def _record_rate_limit_headers(self, response: httpx.Response) -> None:
        """Parses and stores rate-limit headers from a response, if present.

        Delegates header-name parsing to `parse_rate_limit_headers`, which
        subclasses override since every API names these headers differently.

        Args:
            response: The HTTP response to inspect.
        """
        info = self.parse_rate_limit_headers(response.headers)
        if info is not None:
            await self.rate_limit_store.set_remaining(
                self.api_name, info.remaining, info.reset_at
            )

    def parse_rate_limit_headers(self, headers: httpx.Headers) -> Optional[RateLimitInfo]:
        """Extracts (remaining, reset_at) from an API's rate-limit headers.

        Default implementation understands the common GitHub-style headers
        (``X-RateLimit-Remaining`` / ``X-RateLimit-Reset``). Override in
        subclasses for APIs that use different header names (e.g. Reddit's
        ``X-Ratelimit-Remaining`` / ``X-Ratelimit-Reset`` with different
        semantics, or Product Hunt's GraphQL cost-based limiting).

        Args:
            headers: Response headers from the API call.

        Returns:
            A RateLimitInfo if both headers are present and parseable,
            otherwise None.
        """
        remaining = headers.get("X-RateLimit-Remaining")
        reset_at = headers.get("X-RateLimit-Reset")
        if remaining is None or reset_at is None:
            return None
        try:
            return RateLimitInfo(remaining=int(remaining), reset_at=int(reset_at))
        except ValueError:
            logger.debug("Could not parse rate-limit headers: %s", dict(headers))
            return None

    def _parse_retry_after(self, response: httpx.Response, default_seconds: float = 5.0) -> float:
        """Reads a 429 response's Retry-After header, falling back to a default.

        Args:
            response: The 429 response.
            default_seconds: Fallback delay if the header is absent or
                unparseable.

        Returns:
            Seconds to wait before retrying.
        """
        retry_after = response.headers.get("Retry-After")
        if retry_after is None:
            return default_seconds
        try:
            return float(retry_after)
        except ValueError:
            return default_seconds

    def _compute_backoff(self, attempt: int) -> float:
        """Computes exponential backoff with jitter for a retryable failure.

        This backoff exists to be a good citizen toward a service that is
        legitimately struggling (5xx) or asking us to slow down — not to
        evade any block, since none of these APIs are being accessed
        against their terms.

        Args:
            attempt: Zero-indexed retry attempt number.

        Returns:
            Seconds to sleep before the next attempt.
        """
        base = 2 ** attempt
        jitter = random.uniform(0, 1)
        return base + jitter

    def _require_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError(
                f"{type(self).__name__} used before entering its async context. "
                "Use 'async with SomeIngestor(...) as ingestor:'."
            )
        return self._client
