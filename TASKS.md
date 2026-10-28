# Structured System Tasks

## Pending
- [ ] Validation of Modules 1–6 against the requirements matrix (not audited in this pass)
- [ ] Browser/manual check of Modules 7–9 UI against a running PostgreSQL + simulator (only build + API tests were run)
- [ ] Reconcile `frontend/package-lock.json` with `package.json` (`npm ci` fails: lock is missing concurrently, nodemon, prettier, rxjs)
- [ ] Rotate the PostgreSQL password that was previously committed in `config.py` / `CLAUDE.md` (still in git history)
- [ ] Audit-report items for Dashboard fake telemetry (Modules 3–5) — unverified, untouched
- [ ] Learning experience improvements

## In-Progress

## Complete
- [x] Module 7 Policy Engine: policy edit/enable/disable/delete UI, severity-weighted explainable governance score, open-violations endpoint + UI, terminated resources skipped (tests: `backend/tests/test_governance.py`)
- [x] Module 8 Cost Forecaster: validated budget create/edit/delete, threshold-aware alerts, `/cost/summary`, explainable wastage rules, labelled and de-duplicated forecast (tests: `backend/tests/test_cost.py`)
- [x] Module 9 Report Generator: date filters, governance PDF/CSV, governance section in summary PDF, CSV formula guard, UI filters (tests: `backend/tests/test_reports.py`)
- [x] Docs: `docs/PRD_MODULES_7_TO_9.md`, `docs/IMPLEMENTATION_PLAN.md`, `docs/REQUIREMENTS_TRACEABILITY.md`, `docs/IMPLEMENTATION_EXPLANATION.md`
- [x] Hardcoded DB credentials removed from `config.py` and `CLAUDE.md`; test config uses in-memory SQLite

> *Note: Keep these tasks consistently updated. Mark tasks as pending / in-progress / complete as work progresses.*
