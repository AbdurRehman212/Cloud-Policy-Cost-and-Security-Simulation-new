# Implementation Plan — Modules 7–9

Order: test harness → M7 → M8 → M9 → handover. Each step is tested before the next.

0. **Harness** — `TestingConfig` uses `TEST_DATABASE_URL` or in-memory SQLite; `backend/tests/conftest.py` (app, org with owner/viewer/outsider, JWT headers); `pytest.ini`. Remove the hardcoded DB password from `config.py` (env-only, credential-free local fallback).
1. **M7** — severity-weighted score + latest-state helpers in `governance_engine`; routes `GET /violations`, `GET /score`; skip terminated resources; `Governance.jsx` edit / toggle / delete, violations table, score breakdown. Tests: `tests/test_governance.py`.
2. **M8** — budget validation + `PUT/DELETE /budgets/<id>`; `GET /summary`; explainable wastage in `cost_forecaster.detect_wastage`; labelled, de-duplicated forecast; `CostManagement.jsx` budget edit/delete + labels. Tests: `tests/test_cost.py`.
3. **M9** — date filters, governance PDF/CSV, governance section in summary PDF; `Reports.jsx` filters + governance buttons. Tests: `tests/test_reports.py`.
4. **Handover** — update `TASKS.md`, traceability statuses, write `IMPLEMENTATION_EXPLANATION.md`; run pytest and `npm run build`.

Risks: runtime is PostgreSQL while tests use SQLite (touched code uses no PG-specific SQL; JSON/Enum columns are portable). Frontend dependencies are not installed (`npm ci` needed before build).
