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
| 5 Release readiness | **Partial** | Pinned backend deps now match the tested environment; CI workflow added but **not yet executed on GitHub**; 29 npm advisories in production dependencies after the pre-publication pass (0 critical, 13 high — all inside the react-scripts build toolchain; was 62, then 57; transitive via `react-scripts` — **M/H**, needs a toolchain migration, not done); no migrations baseline (above). |
| 6 Maintenance | **Good** | Model version + `GET /api/security/model-info`; runbook; ML evidence note; some `print()` logging remains in routes (**L**). |

## 2. Modules 1–9 verification matrix

| Module | Status | Evidence |
|---|---|---|
| M1 Authentication | PASS | register/login/refresh/profile, duplicate/weak/invalid input, token required on every non-public route (sweep) |
| M2 Organization | PASS (after fixes) | invites end-to-end, role rules, owner-only delete, soft-deleted orgs denied, spoofing blocked |
| M3 Data Generator | PASS | determinism, bounds, business-hour effect, dataset baseline (`test_data_generator.py`) |
| M4 Resource Simulator | PASS | lifecycle, metrics, autoscaler quota/termination safeguards (`test_simulation.py`), UI create + live metrics |
| M5 Resource Viewer | PASS | list/metrics/detail, foreign-org 403, realtime stream now connects in dev |
| M6 Threat Detector | **PASS with documented limitation** | retrained without leakage, evaluated, versioned; since the M10–12 pass it also detects the simulator's attack scenarios (synthetic-data evidence only — see `ML_EVIDENCE.md`) |
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
**Member-role rows are now test-evidenced**: the shared fixture has a `member` user and `test_member_role_matrix_across_modules` checks resources, compliance checks, governance, budgets, invitations, attack simulation, remediation and audit scope for that role.

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
| S10 | **M, fixed (M10–12 pass)** | No rate limiting or lockout on login (ASVS V2.2) | 5 failed sign-ins in 15 min lock the account (counted from the persisted audit trail, reset by a success); 50 failed attempts per client IP per 15 min → 429; `test_login_is_throttled_after_repeated_failures`. Register/forgot-password are still not throttled. |
| S11 | **L, fixed (M10–12 pass)** | Logout did not invalidate the access token | logout revokes refresh **and** access token; every request checks the blocklist; `test_logout_revokes_access_and_refresh_tokens`, e2e logout step. Password change does not yet revoke other sessions. |
| S12 | **L, open** | An earlier local database password (role `abdur`) remains in already-published git history. Checked: that role does not exist on the current development server, so it cannot authenticate here; it may still exist on the previous machine | change or drop it there; history not rewritten |

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

## 9. Modules 10–12 pass (branch `feature/modules-10-12-completion`)

| Area | Finding (evidence) | Action |
|---|---|---|
| Correctness (H) | Simulator and `/security/analyze?auto_remediate` stored `RemediationAction` rows with status `success` although nothing was executed (270 rows in the local DB) | Recommendation and execution separated; rows only written by verified execution; legacy rows kept, tenant back-filled, shown as "legacy, never applied" |
| Correctness (M) | Simulated attacks saved as `contained` with no containment; confidence hard-coded 0.95 | Saved `active`; confidence = detector agreement |
| Correctness (M) | Policy compiler silently ignored unknown keys (`required_tags=owner` → a policy that checks nothing) — found by the new e2e scenario | Unknown keys rejected (UC09 exception); `tag=owner` = tag must exist |
| Race (M) | Audit timeline could show unfiltered results after filtering (stale response overwrote a newer one) — seen in e2e screenshots | Request-sequence guard in Audit and Remediation pages; e2e assertion added |
| Concurrency (M) | Two simultaneous executions of one remediation | Row lock + status re-check; `test_concurrent_execution_runs_once` (PostgreSQL, 3/3 runs) |
| Duplicate logic (L) | Three audit writers, one importing a non-existent module | One `audit_service`; dead module removed |
| ML (H) | Train/serve feature mismatch (4 of 10 features sent as 0) + domain gap | Shared telemetry formula, synthetic simulator training rows, disjoint evaluation seeds (`ML_EVIDENCE.md`) |
| Settings (M) | Default organization accepted any id; string "false" stored as true; partial writes before validation errors; theme only applied on the Settings page; default view/date format/alerts unused | Whole-payload validation, membership check, strict booleans, applied app-wide, alert feed |
| Schema evolution (M, partly open) | `create_all` cannot add columns to existing databases | `utils/schema_upgrade.py`: idempotent, additive-only DDL on start (PostgreSQL); verified on the live DB (users/orgs unchanged). A real Alembic baseline is still not created. |

Tests at the end of this pass: **121 backend tests on PostgreSQL** (57 before), **29 Playwright tests** (20 before) incl. the
cross-module scenario and the 4-width accessibility sweep now covering `/remediation` and `/audit`; frontend production
build compiles with `CI=true`.

Skills: installed skills were reviewed (Ponytail, Agent Browser, Playwright Best Practices, Systematic Debugging,
Verification Before Completion, Vercel React, Supabase Postgres, Web Design Guidelines). A skills.sh check found no maintained
security-review or ML-evaluation skill that adds to Claude Code's built-in `/code-review` and `/security-review` and the
scripted evaluation, so **nothing new was installed**.

## 10. Pre-publication pass (GitHub push)

| Area | Finding | Action / evidence |
|---|---|---|
| Backend dependencies | pip-audit: 51 advisories in 9 pinned packages (PyJWT 2.8 had 19) | Upgraded Flask 3.1.3, Flask-SQLAlchemy 3.1.1, Flask-JWT-Extended 4.7.1, PyJWT 2.15.0, Flask-CORS 6.0.0, Flask-Mail 0.10.0, Flask-SocketIO 5.7.2, python-socketio 5.18.0, eventlet 0.40.3, gunicorn 22.0.0, requests 2.33.0, python-dotenv 1.2.2, pytest 9.0.3, pytest-flask 1.3.0. Remaining: scikit-learn PYSEC-2024-110 (TfidfVectorizer stop words; not used here; upgrading would change the evaluated model) — ignored explicitly in CI with this justification. |
| Breaking change (H) | PyJWT ≥ 2.10 rejects a non-string `sub`; the app issued integer identities → every protected route 422 | `user_identity_loader` writes the id as a string; `app/utils/identity.get_jwt_identity` returns it as int for the 84 call sites |
| Breaking change (H) | Flask-SocketIO 5.3.6 is incompatible with Flask 3.1 (every socket event crashed) — **missed by unit tests, caught by Playwright** | Flask-SocketIO 5.7.2; new `tests/test_realtime.py` exercises the /metrics namespace so CI catches it without a browser |
| Correctness (M, pre-existing) | Cost tests and three app paths mixed local and UTC dates; between 00:00 and 05:00 PKT costs fell outside "today" | budget period, reference forecast and month-to-date cost use UTC like the stored records; tests use UTC |
| UI race (M) | Settings form re-initialised when a second settings fetch arrived, wiping text the user was typing (intermittent e2e failure) | form re-initialised only when the saved version (`updated_at`) changes |
| Migration verification | none in CI | `tests/test_schema_upgrade.py` rebuilds the pre-M10 schema, runs the upgrade twice, checks columns, constraints, indexes, back-fill and kept rows (PostgreSQL) |
| Frontend dependencies | 57 production advisories (2 critical) | `npm audit fix` (semver-compatible only): 29 remaining, 0 critical; runtime axios 1.21.1, socket.io-parser 4.2.7. Lockfile regenerated with npm 10 so CI's `npm ci` accepts it |
| CI/CD | tag-pinned actions; no e2e, audit or code scanning | `ci.yml`: actions pinned to full commit SHAs, `contents: read`, `persist-credentials: false`, CI-only PostgreSQL services; jobs backend, frontend (CI=true), e2e (Playwright against CI database), dependency audit (fails on any Python advisory except the documented one, and on critical npm advisories). `codeql.yml`: Python + JavaScript, `security-events: write` only on that job |
| Secrets | full-history scan | current database password never committed; `.env` ignored; `backend/.env.example` with placeholders; `logs/` and root documents ignored. Historical: the old `abdur` database password (S12) remains in published history — rotate it wherever that role exists. `API_KEY=`/`postgres:` strings found in history are examples inside third-party skill documentation. |
| Repository settings (not changed) | `main` has no branch protection or ruleset; secret scanning and push protection are enabled; Dependabot security updates disabled | Recommended: a ruleset on `main` requiring the CI and CodeQL checks and a pull request; enable Dependabot alerts/updates for pip, npm and GitHub Actions |
| CI-found defects | Running e2e in CI (Linux) exposed: missing e2e lockfile; job-level `PORT` also captured by the React dev server; logout cleared tokens only after the server replied (reload during the request left the user signed in); 22 px header overflow and a keyboard-inaccessible scroll region on Membership at 1024 px (wider Linux fonts) | all fixed in code; tour test waits for the login page |
| Code scanning | CodeQL (first run): 1 high `py/polynomial-redos` (policy text parser), 4 medium `py/stack-trace-exposure` (exception text in responses) | all 5 fixed (CodeQL marks them fixed; 0 open). Policy text limited to 500 characters |

**Final evidence (GitHub Actions, commit 17ae2fc):** CI — backend 125 passed on PostgreSQL 16, frontend build (CI=true) passed,
Playwright 29 passed, pip-audit "No known vulnerabilities found, 2 ignored" (the documented scikit-learn advisory), npm audit 0 critical;
CodeQL Python and JavaScript succeeded with 0 open alerts; secret scanning 0 alerts.

## 11. Final security hardening (branch `feature/final-security-hardening`)

| Area | Finding | Action / evidence |
|---|---|---|
| Rate limiting (S10 rest) | register, forgot-password, reset and verify-email were unlimited | in-process limits (`app/utils/rate_limit.py`); `tests/test_auth_hardening.py` |
| Enumeration | lockout answered only for existing accounts; timing differed | identical answer for unknown addresses; dummy hash check; background mail |
| **Password-reset poisoning (H)** | reset and invitation links were built from the request `Host` header | links use `FRONTEND_BASE_URL`; `test_reset_link_ignores_a_forged_host_header` |
| **Open redirect (M)** | Login/Register followed `?redirect=` unchecked (incl. `/\host`) | `frontend/src/utils/safeRedirect.js` (11 unit tests) + e2e `security.spec.js` |
| Token confusion (M) | verification and reset tokens shared a table without purpose; reset tokens lived 24 h | purpose-bound tokens, reset 1 h, newest link only |
| Sessions (S11 rest) | password change/reset did not end other sessions | `password_changed_at` vs token `iat` (UTC); change-password returns fresh tokens |
| Password hashing | PBKDF2-SHA256, 100k iterations | scrypt for new hashes; upgrade at next login |
| Headers / CORS / secrets | no security headers; CORS and Socket.IO `*`; placeholder secrets accepted | headers + no-store on auth; `CORS_ORIGINS`; production refuses placeholders |
| Migrations | no usable Alembic history | `0001_baseline` + `0002_auth_hardening`, automatic adoption; `tests/test_migrations.py`; real-data copy: 12,209 rows, 0 schema differences |
| Performance | control plane recomputed every organization every 2 s | active organizations only; dashboard p95 511 → 44 ms, throughput 9 → 15 req/s (`scripts/perf_test.py`) |
| Dependencies | npm: 29 (0 critical, 13 high), all highs in react-scripts tooling; react-router open-redirect advisory | mitigated by redirect validation; no compatible fixes remain without replacing react-scripts. Python: 0 (scikit-learn exception re-verified: no text vectorizers, no persisted models) |
| GitHub | no protection on main; Dependabot off | ruleset "Protect main" (PR + 6 required checks, no force-push/deletion); Dependabot alerts + security updates on |
| Historical credential S12 | `abdur` role password in published history | role does not exist on this server (verified); rotate/drop wherever it exists; the current app password was displayed in a support chat and should be rotated by the owner |

Tests at the end of this pass: 145 backend (PostgreSQL), 31 Playwright, frontend build, 11 frontend unit tests.
