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

## Guided tour
New accounts (created < 24 h ago) are offered a tour after login; everyone can replay it with **Help / Take a Tour** in the header. State is per user in the browser (`fyp:tour:v1:<userId>`); clear that key to see the offer again. Steps live in `frontend/src/tour/steps.js`; tests: `e2e/tests/tour.spec.js`.

## Threat-detector evidence
`cd backend && python scripts/evaluate_threat_detector.py` prints the measured metrics quoted in `docs/ML_EVIDENCE.md`.

## Operational notes
- `POST /api/admin/reset-system` deletes data for every organization and is **disabled** (404) unless `ALLOW_SYSTEM_RESET=true` is set in `backend/.env`. Prefer `python backend/scripts/reset_system.py` for a local reset.
- `GET /api/security/model-info` (any signed-in user) shows which threat model version/features the running backend loaded.
- UI/accessibility sweep: `cd e2e && npx playwright test tests/ui-quality.spec.js` (add `E2E_SHOTS=<dir>` to save screenshots). Details and findings: `docs/ENGINEERING_QUALITY_REPORT.md`.
- CI (`.github/workflows/ci.yml`): backend tests on PostgreSQL (incl. schema-upgrade and Socket.IO tests), frontend build with CI=true, Playwright e2e against a CI-only database, dependency audit. `codeql.yml`: code scanning for Python and JavaScript.
- New machine: copy `backend/.env.example` to `backend/.env` and fill in real values.

## Modules 10–12
- Remediation: `/remediation` (UI), `GET /api/remediation/issues`, `POST /api/remediation/plan`, `POST /api/remediation/execute` (admin/owner, `approved: true` for configuration changes), `GET /api/remediation/history`. Acts on simulated rows only.
- Audit trail: `/audit` (UI), `GET /api/audit/events` (filters: `category`, `outcome`, `action`, `q`, `date_from`, `date_to`, `page`, `per_page`), `/api/audit/events/<id>`, `/api/audit/summary`, `/api/audit/me`. Read-only by design.
- Settings: `GET/PUT /api/settings`, `POST /api/settings/reset`, `GET /api/settings/alerts?organization_id=`.
- Schema: on every start `backend/app/utils/schema_upgrade.py` adds missing columns/indexes (additive only, PostgreSQL). No data is deleted.
- Login lockout: 5 failed sign-ins in 15 minutes lock that account for the rest of the window (HTTP 429).
- Cross-module e2e: `cd e2e && npx playwright test tests/modules-10-12.spec.js` (add `E2E_SHOTS=<dir>` for screenshots).
- ML evidence: `cd backend && python scripts/evaluate_threat_detector.py` (≈1 min; prints configurations A and B).

## Final hardening (configuration)
- Migrations run automatically on start (`app/utils/migrations.py`). Manual: `cd backend && flask --app run db upgrade`. Older databases are adopted at `0001_baseline` without data changes. Back up first: `pg_dump -Fc -d cloud_simulator -f backup.dump`.
- New `.env` keys (all optional): `FRONTEND_BASE_URL` (links in e-mails, default http://localhost:3000), `CORS_ORIGINS` (comma-separated), `EMAIL_VERIFICATION_REQUIRED` (true/false), `RATE_LIMIT_ENABLED`, `MIGRATE_ON_START`, `MAIL_SERVER`/`MAIL_PORT`/`MAIL_USE_TLS`/`MAIL_DEFAULT_SENDER`/`MAIL_USERNAME`/`MAIL_PASSWORD`.
- Local mail test: `python -m smtpd -n -c DebuggingServer 127.0.0.1:1025` (Python 3.11) with `MAIL_SERVER=127.0.0.1`, `MAIL_PORT=1025`, `MAIL_USE_TLS=False`.
- Performance test (isolated database only): see `backend/scripts/perf_test.py` header.
- Usability study: `docs/USABILITY_TEST_PROTOCOL.md` (not yet run).
