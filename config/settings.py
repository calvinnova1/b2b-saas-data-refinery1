"""Centralized application settings, loaded from environment variables.

All secrets (API tokens, DB credentials, Redis URL) come from the
environment so nothing sensitive is hardcoded or committed. See
`.env.example` at the project root for the full list of variables this
expects.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application-wide configuration, populated from environment variables.

    Attributes:
        environment: Deployment environment name, e.g. "development",
            "staging", "production". Affects logging verbosity defaults.
        log_level: Root log level, e.g. "INFO", "DEBUG".

        database_url: Async SQLAlchemy connection string for PostgreSQL,
            e.g. "postgresql+asyncpg://user:pass@host:5432/dbname".
        database_pool_size: Max connections in the asyncpg pool.

        redis_url: Connection string for Redis, used both as the Celery
            broker and for shared rate-limit state.

        github_token: Personal access token / GitHub App token used by
            `GitHubIngestor`. Needs at least public read scope.
        github_app_identifier: Honest, descriptive User-Agent string sent
            with every GitHub API request, per GitHub's API guidelines.

        reddit_client_id: PRAW app client ID.
        reddit_client_secret: PRAW app client secret.
        reddit_user_agent: Descriptive user agent for PRAW, per Reddit's
            API rules (must uniquely identify the app).

        producthunt_api_token: OAuth token for Product Hunt's GraphQL API.

        api_secret_key: Used to sign/validate tenant API keys.
        max_retries_default: Default retry count for ingestors that don't
            override it explicitly.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    environment: str = Field(default="development")
    log_level: str = Field(default="INFO")

    database_url: str = Field(
        default="sqlite+aiosqlite:///./dev.db"
    )
    database_pool_size: int = Field(default=20)

    redis_url: str = Field(default="redis://localhost:6379/0")

    github_token: str = Field(default="")
    github_app_identifier: str = Field(
        default="b2b-saas-data-refinery (contact: data-team@example.com)"
    )

    reddit_client_id: str = Field(default="")
    reddit_client_secret: str = Field(default="")
    reddit_user_agent: str = Field(
        default="b2b-saas-data-refinery/0.1 (by /u/your-reddit-username)"
    )

    producthunt_api_token: str = Field(default="")

    api_secret_key: str = Field(default="")
    max_retries_default: int = Field(default=3)


settings = Settings()
