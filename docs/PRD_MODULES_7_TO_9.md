# PRD — Modules 7–9 (Policy Engine, Cost Forecaster, Report Generator)

Scope: Modules 7–9 only. Modules 1–6 are preserved; Modules 10–12 are out of scope.
All infrastructure is simulated; nothing is deployed to a real cloud provider.
Source requirements: `explaination.docx` (module bullets), `chapter_1_to_6.pdf`, `CLAUDE.md`.
`Project Document Guidelines - Ch 6.docx` is a test-plan writing guide (Test Case ID tables); it is not an implementation requirement, but test names here map to Test Case IDs in the traceability matrix.

## Baseline audit (verified from code, 2026-10-28)

| Area | Existing (kept) | Verified gap (to build) |
|---|---|---|
| M7 backend | Policy CRUD, rule compiler (`ai_models/policy_engine.py`), `GovernanceEngine.evaluate_org_policies`, `ComplianceCheck` + `AuditLog` persistence, RBAC (admin/owner write) | Score is an unweighted pass-rate with no explanation; no open-violations endpoint; no score endpoint; terminated resources are evaluated; severity vocabulary inconsistent (`medium`/`warning`) |
| M7 frontend | `Governance.jsx`: create modal, run check, recent checks, audit history | No edit / enable-disable / delete UI; no violations list; no score breakdown |
| M8 backend | `/cost/current`, `/forecast`, `/budgets` (POST/GET), `/optimization`; `CostRecord` written by the simulator; LinearRegression forecaster | No budget edit/delete; no validation on budget create; forecast silently falls back to the 3k reference dataset when an org has no records and is not labelled; every GET inserts duplicate `CostForecast` rows; wastage KMeans always flags a cluster even when all resources are healthy and ignores resource status; alert level ignores configured thresholds; no resource-level cost summary |
| M8 frontend | `CostManagement.jsx`: charts, budget create modal | No budget edit/delete; no forecast basis label; no wastage reasons |
| M9 backend | PDFs (`summary/cost/security`), CSV (`cost`, `security`) in `routes/reports.py`, org membership check | No governance report/CSV; summary PDF has no governance section; no date filters; no tests |
| M9 frontend | `Reports.jsx` download buttons | No filters, no governance report, blob error bodies not parsed |
| Cross-cutting | — | No backend tests exist; `TestingConfig` needs PostgreSQL; `config.py` hardcodes a DB password (flagged; also in `CLAUDE.md`) |

Audit claims re-checked: `audit_report.md` concerns Dashboard/DES telemetry (Modules 3–5). It does not affect Modules 7–9, which read persisted `VirtualMachine`/`Database`/`CostRecord`/`ThreatDetection` rows produced by the simulator. Not modified.

## Module 7 — Policy Engine
Requirements: create policies · validate compliance · track violations · score governance · view audit activity.

- FR7.1 Admin/owner can create, edit, enable/disable and delete policies; other roles read only.
- FR7.2 Rule syntax stays the existing explicit `key=value` / simple-sentence compiler. Invalid rules are rejected with a message.
- FR7.3 "Run check" evaluates every ACTIVE policy against the org's non-terminated VMs/databases and persists a `ComplianceCheck` per (policy, resource).
- FR7.4 `GET /api/governance/violations` returns open violations (non-compliant rows of each policy's latest run), filterable by `severity` and `policy_id`.
- FR7.5 Governance score is explainable: severity-weighted pass rate (`critical=4, high=3, medium=2, low=1`; `warning→medium`, `info→low`). Response includes per-policy weight, pass rate, penalty points and the formula text. `GET /api/governance/score` derives it from the latest persisted run without re-running.
- FR7.6 Every policy create/update/delete/evaluation writes an `AuditLog` row; the UI shows the history.

## Module 8 — Cost Forecaster
Requirements: view cost trends · create budgets · show summaries · detect wastage · display forecasts.

- FR8.1 Trends/summaries come from persisted `CostRecord` only (`/cost/current` kept; add `/cost/summary?days=` with daily trend, per-resource totals and org total).
- FR8.2 Budgets: create (validated: name, amount>0, ordered thresholds, valid date), edit, delete (soft: `is_active=False`). Admin/owner only. Alert level uses the budget's own thresholds.
- FR8.3 Wastage is rule-based and explainable: IDLE (running, CPU<10%) → stop/schedule, saves 100% of monthly cost; UNDERUTILIZED (running, CPU<30% and memory<40%) → downsize, saves 50%. Each finding returns `rule`, `reason`, `estimated: true`. Non-running resources are never flagged.
- FR8.4 Forecast keeps the existing LinearRegression approach. Response states `basis` (`org_cost_records` | `reference_dataset` | `no_data`), `history_days`, `is_estimate: true`. Re-running replaces stored future forecast rows instead of duplicating them.

## Module 9 — Report Generator
Requirements: generate reports · export PDF · export CSV · summarize costs · summarize security.

- FR9.1 Keep existing endpoints. Add `governance.pdf` and `governance.csv` (open violations); add a governance section to `summary.pdf`.
- FR9.2 Optional `start_date`/`end_date` (YYYY-MM-DD) on cost and security reports/CSVs; invalid or inverted dates → 400.
- FR9.3 All data from persisted rows scoped to the caller's org; non-members get 403; every PDF states that data is simulated.
- FR9.4 Frontend: date-range inputs, governance report/CSV buttons, loading and error states.

## Architecture & data flow (unchanged)
Simulator/DES → `VirtualMachine`/`Database`/`CostRecord` → Flask blueprints (`governance_bp`, `cost_bp`, `reports_bp`) → React pages via `services/api.js`. Governance logic lives in `services/governance_engine.py`; cost logic in `routes/cost.py` + `ai_models/cost_forecaster.py`; reports in `routes/reports.py`.

## Database
No new tables and no migration: reuse `policies`, `compliance_checks`, `audit_logs`, `budgets`, `cost_records`, `cost_forecasts`. Budget edit/delete use existing columns; severity weights are computed, not stored.

## Security & tenancy
JWT on every route; org membership checked per request; writes need admin/owner; policy/budget ids are resolved to their org before access (cross-org id → 403). No secrets in code or docs; DB URL comes from `DATABASE_URL`.

## Testing
pytest with in-memory SQLite (`TestingConfig`): rule evaluation, scoring, RBAC, cross-org isolation, budget validation, wastage rules, forecast labelling, PDF/CSV content. Frontend: `npm run build` as compile check.
