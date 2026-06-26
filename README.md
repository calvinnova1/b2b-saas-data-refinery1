# b2b-saas-data-refinery

A Data-as-a-Service pipeline that ingests public B2B software feedback
from **official, permissive APIs only**, enriches it (purchasing intent,
competitive switch graph, dual-axis sentiment), and streams the results
to subscribers over Server-Sent Events.

## Data sources

Every source below is accessed exclusively through its official API,
within that API's documented rate limits and terms of service. No HTML
scraping, no proxy rotation, no user-agent spoofing.

| Source | Method | Status |
|---|---|---|
| GitHub Issues & Discussions | REST API (`github_ingestor.py`) | ✅ Implemented |
| Reddit (r/SaaS, r/startups) | PRAW (`reddit_ingestor.py`) | 🚧 Stub |
| Hacker News | Firebase API (`hackernews_ingestor.py`) | 🚧 Stub |
| Product Hunt | GraphQL API (`producthunt_ingestor.py`) | 🚧 Stub |
| G2 / Capterra / Trustpilot | — | ❌ Out of scope (ToS-prohibited; would require commercial data licensing) |

## Architecture

```
src/
├── ingestion/      # Official API clients (GitHub, Reddit, HN, Product Hunt)
├── processing/      # NLP refinery: intent, competitive switches, sentiment
├── storage/         # Redis-backed shared rate-limit state
├── queue/            # Celery publishers/workers
├── database/         # Async SQLAlchemy models + connection pooling
├── tenancy/          # API-key -> feature-set gating
└── api/
    ├── rest/          # Historical signal queries
    └── stream/        # GET /v1/stream (SSE)
```

## Local development

The project can run in two modes:

1) SQLite local dev flow (fastest, verified)
2) Docker full stack with Postgres + Redis

### SQLite local dev flow

```bash
cp .env.example .env
pip install -r requirements.txt
```

Update `.env` with:

```text
API_SECRET_KEY=dev-local-api-key
DATABASE_URL=sqlite+aiosqlite:///./dev.db
```

Seed the database:

```bash
PYTHONPATH=. vent\Scripts\python.exe scripts/seed_db.py
```

Run the server:

```bash
vent\Scripts\python.exe -m uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000
```

Test the API:

```bash
curl -i http://127.0.0.1:8000/
curl -i -H "Authorization: Bearer dev-local-api-key" http://127.0.0.1:8000/v1/signals
```

### Docker full stack

```bash
docker compose up -d postgres redis
```

Then start the API with Docker on port 8000.

### Verification

The following test file now exists and passes:

- `tests/test_api.py`

This covers the root route, the authorized historical signal API, and the SSE stream connection.

## Rate limiting

`src/ingestion/base_ingestor.py` checks `src/storage/redis_client.py`
before every request and backs off proactively when an API's quota is
nearly exhausted, so multiple worker processes calling the same API never
collectively exceed its documented limit. On `429` responses it honors
`Retry-After`; on `5xx` it retries with exponential backoff + jitter
(max 3 attempts by default).

## Status

This is an early-stage scaffold. `base_ingestor.py` and `github_ingestor.py`
are implemented; everything else under `src/` is a stub with a docstring
describing what it will do. See inline `NOT YET IMPLEMENTED` markers.
