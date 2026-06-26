"""Tests for src/ingestion/*.

TODO: mock httpx responses (e.g. via `respx`) and a fake/mock
RedisRateLimitStore to test:
  - BaseIngestor retry/backoff behavior on 429 and 5xx
  - BaseIngestor proactive throttling via should_throttle()
  - GitHubIngestor.iter_issues() pagination and PR filtering
  - GitHubIngestor.get_comments() pagination
"""
