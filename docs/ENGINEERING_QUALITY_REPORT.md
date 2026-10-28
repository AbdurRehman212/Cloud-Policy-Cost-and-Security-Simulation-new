# Engineering Quality Report — Modules 1–9

Scope: final quality pass before Modules 10–12. Everything below is backed by a test, a measurement or a file reference;
items that could not be verified are marked. Severity: **C**ritical · **H**igh · **M**edium · **L**ow.
Standards used as checklists: OWASP ASVS 5.0 (V2 authentication, V4 access control, V5 validation, V7 logging), OWASP Authorization
Cheat Sheet (deny by default, least privilege, validate on every request), WCAG 2.2 AA, Vercel Web Interface Guidelines.

## 1. SDLC readiness by stage

| Stage | Status | Evidence / gaps |
|---|---|---|
| 1 Requirements | **Partial** | PRD + traceability exist for Modules 7–9 (`docs/PRD_MODULES_7_TO_9.md`, `docs/REQUIREMENTS_TRACEABILITY.md`); Modules 1–6 have no equivalent acceptance-criteria document. Supervisor feedback tracked in `docs/SUPERVISOR_FEEDBACK_ACTION_PLAN.md`. |
| 2 Design | **Partial** | Layered Flask blueprints + service layer. Gaps: schema is created by `db.create_all()` and `backend/migrations` holds only 2 revisions, so column changes to existing databases are not migrated (**M**); CLAUDE.md autoscaling numbers were wrong (fixed). |
| 3 Implementation | **Good after fixes** | 1 Critical, 2 High, 4 Medium defects fixed in this pass (section 3). |
| 4 Verification | **Good** | 57 backend tests (SQLite + PostgreSQL), 48 live API checks, 16 live authorization checks, 20 Playwright tests, route sweeps (no-token, cross-tenant, viewer-write). |
| 5 Release readiness | **Partial** | Pinned backend deps now match the tested environment; CI workflow added but **not yet executed on GitHub**; 62 npm advisories in production dependencies (2 critical, 28 high; transitive via `react-scripts` — **M/H**, needs a toolchain migration, not done); no migrations baseline (above). |
| 6 Maintenance | **Good** | Model version + `GET /api/security/model-info`; runbook; ML evidence note; some `print()` logging remains in routes (**L**). |

## 2. Modules 1–9 verification matrix

| Module | Status | Evidence |
|---|---|---|
| M1 Authentication | PASS | register/login/refresh/profile, duplicate/weak/invalid input, token required on every non-public route (sweep) |
| M2 Organization | PASS (after fixes) | invites end-to-end, role rules, owner-only delete, soft-deleted orgs denied, spoofing blocked |
| M3 Data Generator | PASS | determinism, bounds, business-hour effect, dataset baseline (`test_data_generator.py`) |
| M4 Resource Simulator | PASS | lifecycle, metrics, autoscaler quota/termination safeguards (`test_simulation.py`), UI create + live metrics |
| M5 Resource Viewer | PASS | list/metrics/detail, foreign-org 403, realtime stream now connects in dev |
| M6 Threat Detector | **PASS with documented limitation** | retrained without leakage, evaluated, versioned; **does not detect simulator attack scenarios** (see section 5) |
| M7 Policy Engine | PASS | CRUD, rule validation, weighted score, viewer cannot run checks |
| M8 Cost Forecaster | PASS (after fixes) | per-resource table, consistent totals, budgets use the current period, forecast labelled as estimate |
| M9 Report Generator | PASS | PDFs valid, CSVs scoped, zero-data reports, cross-tenant denied |

## 3. IAM permission matrix and security findings

Role is read from the database on every request, so a role change applies to the next call with the same token (tested).

| Operation | Viewer | Member | Admin | Owner | Non-member |
|---|---|---|---|---|---|
| Read resources, costs, threats, policies, reports/exports | ✔ | ✔ | ✔ | ✔ | ✘ 403 |
| Create/modify resources, security-group rules | ✘ | ✔ | ✔ | ✔ | ✘ |
| Run compliance check, threat analysis (they persist records) | ✘ | ✔ | ✔ | ✔ | ✘ |
| Create policies, budgets, alert rules; simulate attack; resolve threats | ✘ | ✘ | ✔ | ✔ | ✘ |
| Invite members / assign **member, viewer** | ✘ | ✘ | ✔ | ✔ | ✘ |
| Grant, change or remove **admin** | ✘ | ✘ | ✘ | ✔ | ✘ |
| Change or remove the owner | ✘ | ✘ | ✘ | ✘ (immutable) | ✘ |
| Update organization name | ✘ | ✘ | ✔ | ✔ | ✘ |
| Delete organization (soft) | ✘ | ✘ | ✘ | ✔ | ✘ |
| System reset endpoint | disabled for everyone unless `ALLOW_SYSTEM_RESET=true` (dev) |

Verified by tests: viewer/admin/owner/outsider rows for budgets, policies, invites, role changes, deletion, stale privilege, reads.
**Member-role rows are code-derived** (`check_org_access(..., 'member')`): there is no member fixture in the test world, so they are not yet test-evidenced.

### Findings (all fixed unless stated)

| # | Sev | Finding | Fix / test |
|---|---|---|---|
| S1 | **C** | `POST /api/admin/reset-system` let **any logged-in user delete all tenants' VMs, databases, costs, threats, security logs and audit logs** | disabled by default (`ALLOW_SYSTEM_RESET`); `test_system_reset_is_disabled_by_default` |
| S2 | **H** | `/org/invite_demo` (used by the UI) created verified accounts with the fixed password `Demo1234` for any email, and let an admin overwrite the owner's role | no account creation (404 if no account); shared `_may_assign` rule; tests |
| S3 | **H** | Earlier in this project: the URL org was overridden by body/query `organization_id` in `require_org_role` (cross-tenant admin escalation) | fixed earlier; covered by spoof tests |
| S4 | **M** | Admins could grant admin, change/remove other admins | only owners; `test_role_assignment_rules` |
| S5 | **M** | Soft-deleted organizations stayed listed and accessible | `active_membership()` used by all module helpers; `test_deleted_organization_grants_no_access` |
| S6 | **M** | Viewers could run compliance checks and threat analysis (both write records) | 403 for viewers; UI button disabled; viewer-write sweep |
| S7 | **L** | Explicit foreign org returned 200 with an empty body on `/resources/vpcs`, `/network/topology` | 403 |
| S8 | **L** | Assistant endpoint accepted unbounded input | 1,000-character cap (endpoint stays public by design: no tenant data) |
| S9 | **M, open** | 62 known advisories in frontend production dependencies (2 critical, 28 high) | not fixed — needs `react-scripts` replacement; build-time tooling dominates |
| S10 | **M, open** | No rate limiting or lockout on login/register/forgot-password (ASVS V2.2) | not implemented; add Flask-Limiter before any public deployment |
| S11 | **L, open** | JWT has no revocation list; logout does not invalidate an access token (1 h lifetime) | accepted for the FYP; documented |
| S12 | **L, open** | The old `abdur:admin123` database password remains in pushed git history | rotate; history not rewritten |

Checked and found acceptable: token required on every non-public route (sweep); outsider reads return no org data (sweep); SQL is
parameterised through SQLAlchemy (one raw `DELETE` script exists only in the now-disabled reset route and the CLI); passwords hashed with bcrypt;
error responses do not include stack traces in the tested paths.

## 4. Calculations and simulation

| Area | Result |
|---|---|
| Resource lifecycle (PENDING→RUNNING→TERMINATED), termination excluded from cost/optimization/compliance | verified (`test_simulation.py`) |
| Autoscaler | **Fixed (M):** ignored the organization's `max_resources`; now honours `min(100, quota)`. Cooldown 15 s, max 2 VMs per step (code) — the autoscale decision itself lives inside a 700-line function and is only tested via its helpers (**L**, refactor later) |
| Telemetry | deterministic per seed; bounded 0–100 %; business-hour effect |
| Cost precision | **Fixed (M):** `/cost/summary` total, per-resource sum and daily trend now agree (4 dp); `/cost/current` still rounds to 2 dp for display |
| Budgets | **Fixed (M):** a "monthly" budget summed spend since its start date forever; it now measures the current period (monthly/quarterly/yearly windows, month-end clamping tested). Alert boundaries (50/80/100 %) tested. **L, open:** the labels in `alert_thresholds` (warning/critical/exceeded) do not match the levels returned (normal/warning/critical) |
| Wastage | IDLE < 10 % CPU, UNDERUTILIZED < 30 % CPU and < 40 % memory; savings = hourly rate × 730 × fraction; non-running resources never flagged |
| Forecast | linear trend; flat fallback with < 2 days; range = ±1.5 σ of residuals; labelled as an estimate; no backtest (history too short) |
| Governance | weighted score explainable; violations only for non-terminated resources |
| Zero data | all summaries, forecasts and reports return zeros/empty tables, not placeholders |

## 5. ML validation (threat detector)

Full numbers: `docs/ML_EVIDENCE.md`; reproduce: `python backend/scripts/evaluate_threat_detector.py`.

- Label leakage **removed**: `cpu_utilization`, `memory_utilization`, `auth_failures` dropped; `error_rate` flow-derived only. Deployed inputs = training inputs (10 features), enforced by tests.
- Held-out test (stratified 60/20/20, seed 42): accuracy 0.983, macro-F1 0.902, benign false-positive rate 1.0 %. Brute force has 3 test rows, so its metrics are not meaningful. Macro-F1 over 5 splits: 0.922–0.993.
- **Simulator attack scenarios: 0/3 detected for every attack type and intensity.** The model does not transfer to simulator telemetry. Normal simulator telemetry: 600/600 classified normal (not independent ground truth).
- Versioned (`rf-863ed0be8a`) and confirmed loaded by the running backend via `GET /api/security/model-info`.
- **Not production-ready; no accuracy claim on simulator traffic is supported.** Simulated threats are labelled "Simulated (no model score)".

## 6. UI/UX

Checked with the Web Interface Guidelines review skill (installed from `vercel-labs/agent-skills`), axe-core (WCAG 2.2 A/AA) and screenshots.

Fixed (each demonstrated by a failing check or screenshot):
- 68 form labels were not associated with their controls (WCAG 1.3.1/4.1.2) → 58 associated automatically, 8 already wrapped, 1 grouped; unnamed selects/inputs on Security and Profile password toggles labelled; duplicate id removed.
- No skip link → added; first Tab reaches it and moves focus to `#main-content`.
- Colour contrast failures on 6 token patterns → darkened (gray-400→600 text, amber/success/danger/warning 600→700 text, banner label opacity).
- Dashboard "Reconnecting" was permanent: the dev proxy drops Socket.IO; the client now connects to the backend directly in development (production stays same-origin). Covered by a test.
- Guided tour: clicking **Help / Take a Tour** right after a page reload did nothing (the profile had not loaded yet) — found as a flaky test, fixed by queuing the request; 30/30 consecutive passes afterwards.
- Restrained styling: flat banner instead of a blue→violet gradient; removed a non-functional notification bell with a hard-coded red dot and a pulsing "AI ready" indicator; `transition-all` removed from shared styles.
- Developer jargon replaced with plain language (Security, Governance); responsive shell (off-canvas menu).

Verification: 40 page×width combinations (10 pages × 390/768/1024/1440 px) have no horizontal overflow, no duplicate ids and no critical/serious axe violations.

Remaining limitations (honest): axe finds only part of WCAG (no screen-reader or manual keyboard walkthrough of every flow was done); states behind modals are not scanned; moderate/minor axe findings are not asserted; Canvas, Scenarios and Membership pages received only the sweep, not a design review; dark mode was not re-audited for contrast; chart colour-only encoding not reviewed; no visual-regression image diffs were added (screenshots are for manual review only).

## 7. Tests executed in this pass

| Suite | Result |
|---|---|
| Backend pytest — SQLite | 57 passed |
| Backend pytest — PostgreSQL (`cloud_simulator_test`) | 57 passed |
| Backend pytest with no `backend/.env` (CI emulation) | 55 passed |
| Live API checks (running backend, PostgreSQL) | 48/48 |
| Live authorization checks (invites, roles, spoofing, outsider reads) | 16/16 |
| Playwright (regression 9, tour 5, UI quality 4 + 2 keyboard/label checks) | 20 passed (regression 9, tour 5, UI quality 6) |
| Frontend production build | compiles |
| GitHub Actions workflow | written, **not executed** (no remote run yet) |

## 8. Changed files and future-compatibility notes

- Backend: `utils/rbac.py` (`active_membership`), `routes/organization.py` (`_may_assign`), `routes/{resources,governance,security,cost,reports,assistant,admin}.py`, `models/cost.py` (`period_window`), `services/control_plane.py`, `ai_models/threat_detector.py`, `data_sources/real_datasets.py`, `config.py` (`ALLOW_SYSTEM_RESET`), `requirements.txt` (Werkzeug pin).
- Frontend: tour (`src/tour/`), layout shell, label associations across pages, contrast tokens, socket origin (`services/api.js`).
- Tests: `backend/tests/{test_security_sweep,test_authorization,test_simulation,test_threat_model,test_cost}.py`, `e2e/tests/{regression,tour,ui-quality}.spec.js`.
- CI: `.github/workflows/ci.yml` (backend on PostgreSQL + frontend build). Playwright is not in CI because it needs running servers.
- **For Modules 10–12:** (1) new org-scoped routes must use `active_membership()`/`require_org_role` — the route sweeps will fail any route that is public, leaks another tenant's data, or lets a viewer write, unless it is added to the allowlists with a reason; (2) role changes must go through `_may_assign`; (3) add `data-tour` attributes and steps in `src/tour/steps.js`; (4) form fields need `id` + `<label htmlFor>`; (5) schema changes need a real Alembic baseline first; (6) any ML component needs a documented dataset, split, metrics and a version like the detector's.
