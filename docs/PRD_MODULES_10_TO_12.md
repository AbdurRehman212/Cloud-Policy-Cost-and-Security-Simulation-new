# PRD and Traceability — Modules 10–12

Source: *2212399-2212396-2312462 Cloud Policy Cost and Security Simulator - 6 Chapters (1).pdf* —
§1.2 (module features), §2 Sprints 10–12, FR15, UC10 (§4.3.10), UC13 (§4.3.13), Figures 4.12/4.15,
Tables 5.2 / 5.5 / 5.6 / 5.22, Tables 6.10 / 6.13 / 6.24.

**Module numbering** follows §1.2 and the Sprint 10–12 text: M10 Remediation Agent, M11 Audit Trail,
M12 User Settings. **Documentation discrepancy (recorded, not changed):** the Chapter 2 timeframe
table orders sprints differently (Sprint 9 Remediation Agent, 10 User Settings, 11 Cost Forecaster,
12 Audit Trail).

**Pass-marked test cases in the PDF were not taken on trust.** Each was re-implemented as an automated
test and run against the current code on PostgreSQL (results below are from actual runs).

## 1. Status before this work (verified in code at commit ef799a6)

| Area | Found | Problem |
|---|---|---|
| M10 | `ai_models/remediation_agent.py` (rules labelled "Q-learning"; the Q-table was never trained), `RemediationAction` model | No issue list, no execution, no UI. `/security/analyze?auto_remediate` and the simulator stored `status='success'` rows although **nothing was changed** (270 such rows in the local DB). Simulated attacks were saved as `contained` with no containment. |
| M11 | `AuditLog` model; three writers (`governance_engine`, `operational_event_service`, `activity_timeline` — the last imported a non-existent module) | No central service, no categories/outcome, no auth/org/budget/report/settings events, no audit UI beyond a governance card, rows editable through the ORM. |
| M12 | `UserSettings`, `NotificationPreference`, `/api/settings` GET/PUT, Settings page | Default organization not checked against membership; booleans accepted from strings; partial writes before validation errors; no restore defaults; theme applied only while the Settings page was open; default view, date format and alert preferences **used nowhere** (e-mail/SMS/push toggles had no delivery). |

## 2. Requirements → implementation → tests

| ID | Requirement (PDF) | Backend | Frontend | DB | IAM | Acceptance / tests | Status |
|---|---|---|---|---|---|---|---|
| R10.1 | UC10-1/2 display threats and violations; §1.2 alert handling | `remediation_service.list_issues` (open threats, latest-run violations, idle VMs); `GET /api/remediation/issues` | `pages/Remediation` issue list + type filter | `threat_detections`, `compliance_checks`, `virtual_machines` | any member (read) | `test_issues_list_threats_violations_and_idle_resources` | DONE |
| R10.2 | UC10-3/4 select issue, recommended actions; recovery guidance | `remediation_agent.recommend` (deterministic rules, each with its reason) + `build_plan` (preview before/after, consequence, recovery, applicability); `POST /api/remediation/plan` | plan panel | — | any member (read) | UT-50..54 → `test_ut50…test_ut54`; `test_ddos_plan_has_explanations_consequences_and_preview` | DONE |
| R10.3 | UC10-5 execute; automated response / mitigation / threat containment | `execute`: admin/owner only, explicit `approved=true` for configuration changes, only recommended+applicable actions, row lock (`SELECT … FOR UPDATE`), savepoint, rollback on any failure | approval checkbox, execute button, outcome panel | `remediation_actions` (+ organization_id, issue_type, issue_key, resource_type, resource_id, assigned_to) | admin, owner | `test_execute_ddos_…`, `test_brute_force_blocks_source_ip…`, `test_approval_is_required…`, `test_only_admins_and_owners_execute[viewer/member]`, `test_actions_not_recommended_cannot_be_injected`, `test_concurrent_execution_runs_once` (PostgreSQL) | DONE |
| R10.4 | UC10-6 update issue status (only after verification) | each action re-read after it runs; violations re-evaluated with the policy engine; threat → resolved / contained / under_review | status badge, history | `threat_detections.status`, `compliance_checks.remediation_applied` | — | `test_public_unencrypted_database_violation_is_fixed_and_verified`, `test_partial_fix_of_violation_fails_verification_and_rolls_back`, `test_low_confidence_threat_goes_to_review_without_changes` | DONE |
| R10.5 | UC10 exception: failure → message, issue unresolved | failed rows + `remediation_failed` audit; no state kept | error panel | — | — | `test_failed_action_rolls_back_everything…`, `test_failure_during_execution_is_rolled_back_and_recorded` | DONE |
| R10.6 | UC10-7 record in audit trail | `remediation_recommended / approved / executed / failed / denied` | — | `audit_logs` | — | `test_execute_ddos…`, `test_resource_lifecycle_and_remediation_appear_in_timeline` | DONE |
| R10.7 | Tenant isolation | issue and target looked up inside the org | — | — | — | `test_cross_tenant_issue_and_target_are_rejected` | DONE |
| R11.1 | FR15, §1.2 activity logging / event tracking / user actions | single `services/audit_service.record_audit` used by every module; category + outcome; secrets redacted; IP only for auth events | — | `audit_logs` (+ category, outcome; org nullable for account events; IPv6 length) | — | `test_cross_module_events_are_recorded`, `test_auth_events_have_no_secrets…`, `test_secrets_are_redacted_recursively` | DONE |
| R11.2 | Change history | old/new values (e.g. settings diff, remediation before/after) | event detail | — | — | `test_settings_change_is_audited_with_diff`, e2e M11 | DONE |
| R11.3 | Timeline records, search, filters, pagination | `GET /api/audit/events` (category, outcome, action, q, date_from/to, page), `/events/<id>`, `/summary`, `/me` | `pages/Audit` timeline grouped by day | indexes on (organization_id, timestamp), category, user_id | owner/admin: whole org; member/viewer: own actions | `test_filters_search_dates_and_pagination`, `test_tenant_isolation_and_least_privilege` | DONE |
| R11.4 | Immutability | ORM `before_update/before_delete` listeners raise; no write endpoints | read-only UI | — | — | `test_audit_rows_cannot_be_updated_or_deleted`, `test_no_write_endpoints_exist` | DONE |
| R12.1 | UC13 edit profile / update account | `profile` section in `PUT /api/settings` (length-checked) | Profile tab | `users`, `user_profiles` | self only (id from JWT) | UT-71 → `test_ut71…`; `test_users_only_change_their_own_settings` | DONE |
| R12.2 | Change theme | validated light/dark; applied on every sign-in (Layout) and cached | Appearance tab | `user_settings.theme` | self | UT-66..68 → `test_ut66…test_ut68`; e2e "applied after reload" | DONE |
| R12.3 | Manage preferences (default view, default org, date format, timezone, inactivity sign-out) | enum/range validation; default org must be an active membership | Dashboard/Appearance/Security tabs; Resources grid/list; idle sign-out | `user_settings` | self + membership | UT-69, IT-20 → `test_ut69…`, `test_it20…`, `test_default_organization_must_be_a_membership`, `test_validation_messages[...]` | DONE |
| R12.4 | Configure alerts (Table 5.2 alert preference) | security on/off + minimum severity, cost on/off + threshold 1–100 %, governance on/off; `GET /api/settings/alerts` | Alerts tab + header alert bell | `notification_preferences` | self, org membership for the feed | UT-70 → `test_ut70…`; `test_alert_feed_follows_preferences` | DONE (in-app only; e-mail/SMS/push not implemented and not offered in the UI) |
| R12.5 | UC13 alternative flow: restore defaults | `POST /api/settings/reset` (profile kept) | Restore defaults | — | self | `test_restore_defaults` | DONE |
| R12.6 | UC13 exception: invalid input → error, nothing saved | validate whole payload before writing | inline error | — | — | `test_invalid_payload_changes_nothing` | DONE |
| X1 | FR16 guided tour covers all modules | `tour/steps.js` +8 steps (26 for owners) | — | — | role-filtered steps | `e2e/tests/tour.spec.js` (5) | DONE |
| X2 | Cross-module scenario (register → … → reports) | — | — | — | — | `e2e/tests/modules-10-12.spec.js` (9 steps) | DONE |

## 3. IAM summary for Modules 10–12

| Action | owner | admin | member | viewer |
|---|---|---|---|---|
| View issues / plan / remediation history | ✓ | ✓ | ✓ | ✓ |
| Execute remediation (with approval) | ✓ | ✓ | ✗ (403, audited as denied) | ✗ |
| View organization audit trail | all events | all events | own events | own events |
| View own account activity (`/audit/me`) | ✓ | ✓ | ✓ | ✓ |
| Edit audit records | ✗ (no endpoint; ORM refuses) | ✗ | ✗ | ✗ |
| Change own settings | ✓ | ✓ | ✓ | ✓ |
| Change another user's settings | ✗ (user id from token only) | ✗ | ✗ | ✗ |

## 4. Out of scope / not implemented (stated honestly)
- E-mail, SMS and push notifications (no delivery channel configured); the stored flags are kept for compatibility but are not shown as working controls.
- Two-factor authentication.
- Automatic (unattended) remediation: every configuration change needs a person's approval by design.
- Remediation acts on simulated rows only (security groups, instance type, status, flags, tags); nothing outside the application is contacted.
