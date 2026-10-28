# Requirements Traceability — Modules 7–9

Status after implementation. VERIFIED = covered by a passing automated test (23 backend tests, `pytest`) and the frontend production build compiled. UI behaviour was not exercised in a browser against PostgreSQL.

| ID | Requirement (explaination.docx) | Code | Before | Now | Test Case ID → test |
|---|---|---|---|---|---|
| M7-1 | Create policies | `routes/governance.py` POST/PUT/DELETE `/policies`; `Governance.jsx` create/edit/toggle/delete | PARTIAL | COMPLETE (API verified) | TC-M7-01..04 → `test_policy_crud_and_audit` |
| M7-2 | Validate compliance | `GovernanceEngine.evaluate_org_policies`, `ai_models/policy_engine.py` | PARTIAL | COMPLETE (API verified) | TC-M7-05..06 → `test_validation_and_violations` |
| M7-3 | Track violations | `GET /governance/violations`, Open Violations card | MISSING | COMPLETE (API verified) | TC-M7-07 → `test_validation_and_violations` |
| M7-4 | Score governance | `GovernanceEngine.compute_score`, `GET /governance/score`, score card | PARTIAL | COMPLETE (API verified) | TC-M7-08..09 → `test_weighted_score_is_explainable`, `test_score_before_any_run` |
| M7-5 | View audit activity | `GET /governance/audit-logs`; history card | COMPLETE | COMPLETE | TC-M7-10 → `test_policy_crud_and_audit` |
| M7-6 | RBAC / isolation | `_require_org_member` + role checks | untested | VERIFIED | TC-M7-11..12 → `test_rbac_and_isolation` |
| M8-1 | View cost trends | `GET /cost/summary`, `/cost/current`; `CostManagement.jsx` charts | PARTIAL | COMPLETE (API verified) | TC-M8-01 → `test_summary_trend_and_per_resource` |
| M8-2 | Create budgets | `POST/PUT/DELETE /cost/budgets`; budget modal + list | PARTIAL | COMPLETE (API verified) | TC-M8-02..05 → `test_budget_validation_and_crud`, `test_budget_rbac_and_isolation`, `test_budget_alert_level_uses_own_thresholds` |
| M8-3 | Show summaries | `/cost/summary` (org + per-resource), `/cost/current` | PARTIAL | COMPLETE (API verified); per-resource table not yet rendered in UI | TC-M8-06 → `test_summary_trend_and_per_resource` |
| M8-4 | Detect wastage | `GET /cost/optimization`, `cost_forecaster.detect_wastage` (IDLE / UNDERUTILIZED rules) | PARTIAL | COMPLETE (API verified) | TC-M8-07..08 → `test_wastage_rules_are_explainable`, `test_no_waste_when_all_healthy` |
| M8-5 | Display forecasts | `GET /cost/forecast` (labelled estimate, `basis`) | PARTIAL | COMPLETE (API verified) | TC-M8-09..10 → `test_forecast_is_labelled_and_not_duplicated`, `test_forecast_without_org_data_is_labelled_not_persisted` |
| M9-1 | Generate reports | `routes/reports.py` PDF builders incl. governance | PARTIAL | COMPLETE (API verified) | TC-M9-01..02 → `test_governance_report_and_summary_section`, `test_generate_endpoint_and_legacy_csv` |
| M9-2 | Export PDF | `/reports/{summary,cost,security,governance}.pdf` | PARTIAL | COMPLETE (API verified) | TC-M9-03 → `test_pdfs_are_valid_and_scoped` |
| M9-3 | Export CSV | `/reports/{cost,security,governance}.csv`, `/reports/export/csv` | PARTIAL | COMPLETE (API verified) | TC-M9-04..05 → `test_cost_csv_filters_and_isolation`, `test_security_csv_and_summary` |
| M9-4 | Summarize costs | `_build_cost_pdf` | COMPLETE | VERIFIED | TC-M9-06 → `test_cost_pdf_content` |
| M9-5 | Summarize security | `_build_security_pdf` | COMPLETE | VERIFIED | TC-M9-07 → `test_security_csv_and_summary` |
| M9-6 | Isolation / bad input | `_authorize`, `_parse_range` | PARTIAL | VERIFIED | TC-M9-08..09 → `test_pdfs_are_valid_and_scoped`, `test_invalid_dates_rejected` |

## Known contradictions / flags
- `CLAUDE.md` and `backend/app/config.py` contained a PostgreSQL URL with a password. Both are now redacted/env-only, but the password remains in git history and should be rotated.
- `CLAUDE.md` route list differs from the code (`/governance/compliance`, `/cost/summary` (was absent), `/cost/history`, `/cost/budget`). Code is authoritative; `/cost/summary` now exists.
- `cost_forecaster.load_historical_frame` substitutes the bundled 3k reference dataset when an org has no cost records. It is now labelled `basis: reference_dataset` and never persisted as that org's forecast.
- `Project Document Guidelines - Ch 6.docx` is a test-plan writing guide, not a feature requirement.
- `frontend/package-lock.json` is out of sync with `package.json`.
