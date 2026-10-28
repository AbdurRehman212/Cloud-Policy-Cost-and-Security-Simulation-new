# Implementation Explanation — Modules 7–9

Written for reuse in the FYP documentation chapters. Modules 1–6 were preserved (not audited or modified in this pass); Modules 10–12 are out of scope. All infrastructure is simulated.

## 1. Verification actually performed
| Check | Result |
|---|---|
| `pytest` (backend/tests, in-memory SQLite) | 23 passed |
| `npm run build` (CRA) | Compiled successfully |
| Existing frontend unit test (`dashboardSlice.test.js`) | 4 passed |
| Browser / PostgreSQL / live simulator run | **Not performed** (no PostgreSQL available here) |

Tests run on SQLite; production uses PostgreSQL. The touched code uses no PostgreSQL-specific SQL, but this difference is a residual risk.

## 2. Module 7 — Policy Engine
**What it does:** admins/owners create, edit, enable/disable and delete policies; any member can run a compliance check, view open violations, the governance score and the audit history.

- **Rules** (`ai_models/policy_engine.py`, unchanged): deterministic compiler for `key=value` rules (`resource_type`, `max_cpu`, `max_memory`, `max_network`, `encryption`, `public_access`, `tag`, `name_prefix`, `name_regex`, `severity`) and a few natural-language patterns. Not an ML/LLM interpreter.
- **Evaluation** (`services/governance_engine.py`): each ACTIVE policy is evaluated against the org's non-terminated VMs and databases; one `ComplianceCheck` row per policy/resource is stored with the violation details.
- **Score:** `score = 100 × Σ(weight × compliant checks) / Σ(weight × total checks)`, weights critical 4, high 3, medium 2, low 1 (`warning`→medium, `info`→low). With no checks the score is 100 and `evaluated` is false. The API returns the formula and a per-policy breakdown (weight, violations, penalty points).
- **Open violations:** failed checks from each active policy's most recent run (`get_latest_state`).
- **Audit:** `AuditLog` rows for policy create/update/delete and every evaluation.

| Endpoint | Method | Role |
|---|---|---|
| `/api/governance/policies` | GET / POST | member / admin+ |
| `/api/governance/policies/<id>` | PUT / DELETE | admin+ |
| `/api/governance/compliance/check` | POST | member |
| `/api/governance/compliance/checks` | GET | member |
| `/api/governance/violations?severity=&policy_id=` | GET | member (new) |
| `/api/governance/score` | GET | member (new) |
| `/api/governance/audit-logs` | GET | member |

Frontend (`Governance.jsx`): edit/disable/delete on each policy card (managers only), Governance Score card with breakdown, Open Violations card, plus the existing create modal, recent checks and audit history.

## 3. Module 8 — Cost Forecaster
**Data source:** `CostRecord` rows written by the resource simulator (`services/resource_simulator.py`, `cost_calculator.py`). Nothing is mocked.

- **Trends/summaries:** `GET /api/cost/summary?days=` returns the daily trend (zero-filled), previous-period comparison, and per-resource compute/storage/network totals with names. `/cost/current` (month-to-date, by service/day, budgets) is unchanged.
- **Budgets:** `POST /cost/budgets`, `PUT/DELETE /cost/budgets/<id>` (admin+; delete is soft). Validation: name, amount > 0, period ∈ monthly/quarterly/yearly, ISO start date, thresholds positive and ascending. `alert_level` is `normal` / `warning` (≥ threshold 2) / `critical` (≥ threshold 3), using each budget's own thresholds. Spend is bounded by the budget's start/end date.
- **Wastage** (`cost_forecaster.detect_wastage`): running resources only. IDLE: CPU < 10% → stop/schedule, estimated saving = 100% of hourly rate × 730 h. UNDERUTILIZED: CPU < 30% and memory < 40% → downsize, saving 50%. Each item carries `rule`, `reason`, `estimated: true`. This replaces the earlier KMeans approach, which always flagged one cluster even when every resource was healthy; the existing sklearn dependency is still used by the forecaster.
- **Forecast:** unchanged approach (LinearRegression on daily total cost, band ±1.5 × residual std). Response now includes `is_estimate`, `basis` (`org_cost_records` | `reference_dataset` | `no_data`), `history_days`, `method` and a `note` (e.g. fewer than 7 days of history). Org-based forecasts replace the org's stored future `CostForecast` rows instead of appending on every request; reference-dataset forecasts are not stored.

Frontend (`CostManagement.jsx`): forecast card labelled "estimate" with its note; budget list with edit/delete; budget modal reused for edit with client-side validation; recommendations show the triggering rule and "estimated". The per-resource table from `/cost/summary` is not yet displayed in the UI.

## 4. Module 9 — Report Generator
Built from persisted rows only, scoped to the caller's organization.

| Endpoint | Output |
|---|---|
| `/api/reports/summary.pdf` | org overview + cost/threat trends + governance score and open violations |
| `/api/reports/cost.pdf`, `/security.pdf` | cost / security summaries and recent records |
| `/api/reports/governance.pdf` (new) | governance summary, score breakdown, open violations |
| `/api/reports/cost.csv`, `/security.csv`, `/governance.csv` (new) | raw exports |
| `/api/reports/generate` (POST), `/export/csv?type=` | legacy endpoints, now also support governance; unknown report type → 400 |

- `start_date` / `end_date` (YYYY-MM-DD) filter cost and security outputs; invalid or inverted dates → 400. Governance reports reflect the latest check.
- Every PDF states its period and that figures come from simulated resources, not real billing.
- PDF cells are XML-escaped (user-supplied names cannot break ReportLab markup); CSV cells beginning with `= + - @` are prefixed with `'` to prevent spreadsheet formula execution.
- Frontend (`Reports.jsx`): date range, four PDF cards, three CSV exports, loading state, and server error messages parsed out of blob responses.

## 5. Security and tenancy
JWT on every route; membership checked per request; writes require admin/owner; policy and budget ids are resolved to their organization before use, so another tenant's id returns 403. Tests assert 403 for non-members on every new/changed read endpoint and for viewer/outsider writes. Hardcoded DB credentials were removed from `config.py` and `CLAUDE.md` (history still contains them; rotate).

## 6. Database
No new tables or migrations. `Budget.to_dict` gained `period`, `start_date`, `end_date`, `alert_level`; `Budget.get_current_spend` honours `end_date`.

## 7. Tests (backend/tests)
`conftest.py` (two orgs; owner/admin/viewer/outsider tokens), `test_governance.py` (5), `test_cost.py` (8), `test_reports.py` (10 incl. parametrized). Test IDs map to `REQUIREMENTS_TRACEABILITY.md`.

## 8. Changed files
Backend: `config.py`, `models/cost.py`, `ai_models/cost_forecaster.py`, `services/governance_engine.py`, `routes/{governance,cost,reports}.py`, `pytest.ini`, `tests/*`. Frontend: `pages/{Governance/Governance,Cost/CostManagement,Reports/Reports}.jsx`. Docs: `docs/*`, `TASKS.md`, `CLAUDE.md` (credentials redacted).

## 9. Limitations and remaining work
- UI not exercised in a browser against PostgreSQL; run `python run.py` + `npm start` and click through each page.
- Wastage thresholds and savings fractions are fixed heuristics, not configurable.
- Forecast is a linear trend; seasonality is not modelled. `auto_remediate` and `auto_shutdown_at_threshold` remain metadata flags — nothing acts on them.
- Governance policies cannot target tags/names on resources other than VMs/databases; network/security-group resources are not evaluated.
- Per-resource cost table not yet rendered in `CostManagement.jsx`.
- Modules 1–6 and the `audit_report.md` dashboard-telemetry concerns were not audited here.
- `frontend/package-lock.json` is out of sync (`npm ci` fails); `npm install --no-package-lock` was used.
