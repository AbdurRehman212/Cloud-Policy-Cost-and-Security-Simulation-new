# Local Runbook (Windows)

## Prerequisites
PostgreSQL 16 service running (starts automatically), Node 24, `uv`-managed Python 3.11 in `backend/.venv`, Google Chrome (for e2e).

## `backend/.env` (git-ignored, never commit)
Required keys: `DATABASE_URL`, `SECRET_KEY`, `JWT_SECRET_KEY`, `PORT`, `FLASK_ENV`.
`DATABASE_URL=postgresql://<user>:<password>@localhost/cloud_simulator`. Tables are created on first start.
Back this file up outside the repo; rotate the DB password if it was ever shared.

## Start
```
cd backend  && set PYTHONUTF8=1 && .venv\Scripts\python.exe run.py     # http://localhost:5000
cd frontend && npm start                                                # http://localhost:3000
```

## Tests
```
cd backend && .venv\Scripts\python.exe -m pytest -q                     # SQLite, fast
set TEST_DATABASE_URL=postgresql://<user>:<password>@localhost/cloud_simulator_test && .venv\Scripts\python.exe -m pytest -q   # PostgreSQL
cd e2e && npm install && npx playwright test                            # needs both servers running
```
`E2E_BASE_URL` overrides the frontend URL. The suite registers a fresh user each run.
