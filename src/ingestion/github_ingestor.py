"""GitHub Issues & Discussions ingestor, built on the official REST API.

Fetches public issues (and their comments) from a given repository using
GitHub's documented REST API v3. Authenticates with a personal access token
or GitHub App token supplied via configuration — never scrapes github.com
HTML, and never touches anything outside what the token's scopes and the
repo's visibility already permit.

GitHub's actual rate-limit header names (``X-RateLimit-Remaining`` /
``X-RateLimit-Reset``) happen to match the defaults `BaseIngestor` assumes,
so no header-parsing override is needed here — that's GitHub-specific
convenience, not a coincidence to rely on for other APIs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional

from src.ingestion.base_ingestor import BaseIngestor
from src.storage.redis_client import RedisRateLimitStore

logger = logging.getLogger(__name__)

GITHUB_API_BASE_URL = "https://api.github.com"


@dataclass(frozen=True)
class GitHubIssue:
    """A single GitHub issue or pull request, as returned by the Issues API.

    Attributes:
        id: GitHub's internal numeric ID for the issue.
        number: The issue number as shown in the repo UI (e.g. #42).
        title: Issue title.
        body: Issue body text (may be empty/None for title-only issues).
        state: "open" or "closed".
        labels: Label names attached to the issue.
        comment_count: Number of comments, per the API's `comments` field.
        html_url: Public URL to the issue on github.com.
        created_at: ISO-8601 creation timestamp.
        updated_at: ISO-8601 last-updated timestamp.
    """

    id: int
    number: int
    title: str
    body: Optional[str]
    state: str
    labels: list[str]
    comment_count: int
    html_url: str
    created_at: str
    updated_at: str

    @classmethod
    def from_api_payload(cls, payload: dict[str, Any]) -> "GitHubIssue":
        """Builds a GitHubIssue from a raw GitHub API JSON object."""
        return cls(
            id=payload["id"],
            number=payload["number"],
            title=payload.get("title", ""),
            body=payload.get("body"),
            state=payload.get("state", "unknown"),
            labels=[label["name"] for label in payload.get("labels", []) if "name" in label],
            comment_count=payload.get("comments", 0),
            html_url=payload.get("html_url", ""),
            created_at=payload.get("created_at", ""),
            updated_at=payload.get("updated_at", ""),
        )


@dataclass(frozen=True)
class GitHubComment:
    """A single comment on a GitHub issue or pull request.

    Attributes:
        id: GitHub's internal numeric ID for the comment.
        body: Comment text.
        author_login: Username of the comment author (None if the account
            has since been deleted).
        created_at: ISO-8601 creation timestamp.
    """

    id: int
    body: str
    author_login: Optional[str]
    created_at: str

    @classmethod
    def from_api_payload(cls, payload: dict[str, Any]) -> "GitHubComment":
        """Builds a GitHubComment from a raw GitHub API JSON object."""
        user = payload.get("user") or {}
        return cls(
            id=payload["id"],
            body=payload.get("body", ""),
            author_login=user.get("login"),
            created_at=payload.get("created_at", ""),
        )


class GitHubIngestor(BaseIngestor):
    """Fetches public issues and comments from a repo via GitHub's REST API.

    Example:
        store = RedisRateLimitStore(redis_url="redis://localhost:6379/0")
        async with GitHubIngestor(token=os.environ["GITHUB_TOKEN"],
                                   rate_limit_store=store) as ingestor:
            async for issue in ingestor.iter_issues("psf", "requests"):
                comments = await ingestor.get_comments("psf", "requests", issue.number)
    """

    def __init__(
        self,
        token: str,
        rate_limit_store: RedisRateLimitStore,
        app_identifier: str = "b2b-saas-data-refinery (contact: data-team@example.com)",
        max_retries: int = 3,
        request_timeout_seconds: float = 30.0,
        per_page: int = 100,
    ) -> None:
        """Initializes the GitHub ingestor.

        Args:
            token: A GitHub personal access token or GitHub App installation
                token with at least `public_repo` read scope. Never embed
                this directly in code — load it from environment/secrets.
            rate_limit_store: Shared Redis-backed rate-limit tracker.
            app_identifier: A clear, honest identifier for this application,
                sent as the User-Agent. GitHub's API requires a descriptive
                User-Agent and recommends including contact info — this is
                the opposite of spoofing a browser UA.
            max_retries: Max retry attempts for 429/5xx responses.
            request_timeout_seconds: Per-request timeout.
            per_page: Page size for paginated endpoints (GitHub max is 100).
        """
        super().__init__(
            api_name="github",
            base_url=GITHUB_API_BASE_URL,
            rate_limit_store=rate_limit_store,
            default_headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": app_identifier,
            },
            max_retries=max_retries,
            request_timeout_seconds=request_timeout_seconds,
        )
        self.per_page = per_page

    async def iter_issues(
        self,
        owner: str,
        repo: str,
        state: str = "all",
        since: Optional[str] = None,
    ) -> AsyncIterator[GitHubIssue]:
        """Yields issues for a repo, paginating automatically.

        Args:
            owner: Repository owner/org, e.g. "psf".
            repo: Repository name, e.g. "requests".
            state: "open", "closed", or "all".
            since: Optional ISO-8601 timestamp; only issues updated at or
                after this time are returned. Use this for incremental
                ingestion instead of re-fetching the whole repo each run.

        Yields:
            GitHubIssue instances, oldest page first, in the order GitHub
            returns them.

        Raises:
            IngestorHTTPError: If a page fetch fails after retries.
        """
        page = 1
        while True:
            params: dict[str, Any] = {
                "state": state,
                "per_page": self.per_page,
                "page": page,
            }
            if since is not None:
                params["since"] = since

            logger.debug(
                "Fetching issues page %d for %s/%s (state=%s)", page, owner, repo, state
            )
            response = await self.get(f"/repos/{owner}/{repo}/issues", params=params)
            payloads = response.json()

            if not payloads:
                logger.info(
                    "Finished paginating issues for %s/%s after %d page(s)",
                    owner,
                    repo,
                    page - 1,
                )
                return

            for payload in payloads:
                # The Issues endpoint also returns pull requests; skip those
                # since PRs aren't "feedback signal" data for this pipeline.
                if "pull_request" in payload:
                    continue
                yield GitHubIssue.from_api_payload(payload)

            page += 1

    async def get_comments(
        self, owner: str, repo: str, issue_number: int
    ) -> list[GitHubComment]:
        """Fetches all comments on a single issue.

        Args:
            owner: Repository owner/org, e.g. "psf".
            repo: Repository name, e.g. "requests".
            issue_number: The issue's number (not its internal ID).

        Returns:
            All comments on the issue, oldest first.

        Raises:
            IngestorHTTPError: If the fetch fails after retries.
        """
        comments: list[GitHubComment] = []
        page = 1
        while True:
            response = await self.get(
                f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
                params={"per_page": self.per_page, "page": page},
            )
            payloads = response.json()
            if not payloads:
                break
            comments.extend(GitHubComment.from_api_payload(p) for p in payloads)
            page += 1

        logger.debug(
            "Fetched %d comment(s) for %s/%s#%d", len(comments), owner, repo, issue_number
        )
        return comments
