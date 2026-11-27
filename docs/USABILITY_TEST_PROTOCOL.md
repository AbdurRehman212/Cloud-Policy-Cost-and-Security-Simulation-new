# Usability Test Protocol (not yet conducted)

Status: **protocol only — no participant sessions have been run and no results exist.** Record real
results in the table at the end; do not fill it in from expectations.

## Goal
Check whether first-time users (students new to cloud computing) can complete the main learning
journey across all twelve modules without help, and find the steps where they get stuck
(Supervisor feedback F3).

## Participants
- 5 participants (enough to find most major usability problems), e.g. BS students who have not used the
  simulator. Record only a participant code (P1–P5), study programme and self-rated cloud experience
  (none / some / experienced). No names or e-mail addresses.
- Informed consent: explain the purpose, that the product (not the person) is being tested, that they can
  stop at any time, and that only anonymous notes are kept.

## Setup
- Laptop with the application running locally (frontend http://localhost:3000), a fresh test account per
  participant created by the moderator, screen recording only with consent.
- Moderator reads tasks aloud; participant thinks aloud; moderator does not help unless the participant is
  stuck for 3 minutes (record as "assisted").

## Tasks (12 modules)
| # | Task given to the participant | Module(s) | Success criterion |
|---|---|---|---|
| T1 | Sign in with the account provided and skip or follow the guided tour | M1, tour | Dashboard visible |
| T2 | Find which organization you are in and what your role is | M2 | Says organization and role |
| T3 | Create a small virtual machine named `web-test` | M3, M4 | VM shows Running |
| T4 | Open the live metrics of that VM | M5 | Metrics chart visible |
| T5 | Simulate a DDoS attack and find it in the threat list | M6 | Threat listed |
| T6 | Create a policy requiring the tag `owner` and run a compliance check | M7 | Violation listed |
| T7 | Find the monthly cost forecast and create a budget of 50 | M8 | Budget visible |
| T8 | Fix the DDoS threat using the Remediation page | M10 | Status Resolved |
| T9 | Find the record of what you just fixed | M11 | Event opened |
| T10 | Switch to dark theme and set the date format to DD/MM/YYYY | M12 | Applied after reload |
| T11 | Download the security report as CSV | M9 | File downloaded |

## Measures (per task)
Completion (unaided / assisted / failed), time on task, number of errors, and a short note of where the
participant hesitated. After all tasks: System Usability Scale (SUS, 10 standard questions, score 0–100)
and two open questions ("What was most confusing?", "What would you change first?").

## Analysis
- Task completion rate and median time per task; SUS mean and range (SUS above 68 is commonly read as
  above average).
- Group problems by page; rate severity (blocker / major / minor) by how many participants hit them and
  whether they could recover.
- Fix blockers first, then re-test the affected tasks with at least two new participants.

## Results (to be filled in after real sessions)
| Participant | Tasks completed unaided | SUS | Main problems observed |
|---|---|---|---|
| P1 | | | |
| P2 | | | |
| P3 | | | |
| P4 | | | |
| P5 | | | |
