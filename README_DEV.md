Local development notes — quick start (SQLite fallback)

Use this when Postgres/Redis (Docker) aren't available. It runs the app
against a local `dev.db` SQLite file and uses a simple dev API key.

1) Activate the virtualenv (Windows)

PowerShell:

    .\vent\Scripts\Activate.ps1

CMD:

    .\vent\Scripts\activate.bat

2) Install dependencies

    vent\Scripts\pip.exe install -r requirements.txt

3) Ensure `.env` contains these values (or export them in your shell):

    API_SECRET_KEY=dev-local-api-key
    DATABASE_URL=sqlite+aiosqlite:///./dev.db

4) Seed the database

    PYTHONPATH=. vent\Scripts\python.exe scripts/seed_db.py

5) (Optional) Insert a sample signal

    PYTHONPATH=. vent\Scripts\python.exe - <<PY
    from src.database.connection import AsyncSessionLocal
    from src.database.models import Signal
    import asyncio

    async def main():
        async with AsyncSessionLocal() as session:
            s = Signal(tenant_id=1, source='dev', signal_type='note', content='hello', details={'x':1})
            session.add(s)
            await session.commit()
    asyncio.run(main())
    PY

6) Run the FastAPI server (use port 8001 if 8000 is occupied)

    vent\Scripts\python.exe -m uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8001

7) Test endpoints

    # health
    curl -i http://127.0.0.1:8001/

    # historical signals (authorized)
    curl -i -H "Authorization: Bearer dev-local-api-key" http://127.0.0.1:8001/v1/signals

    # SSE stream (opens a streaming connection)
    curl -N -H "Accept: text/event-stream" -H "Authorization: Bearer dev-local-api-key" http://127.0.0.1:8001/v1/stream

8) To run full stack (Postgres + Redis) using Docker (recommended for integration):

    docker compose up -d postgres redis

If you want, I can help you bring up Docker, or try to free port 8000 so the app runs there.
