# Supervisor Feedback — Action Plan

Source: supervisor review of the FYP (Mr. Hasnain Tahir). Status legend: TODO / IN PROGRESS / DONE.
Modules 10–12 are not part of this plan's scope; items below that touch them wait until those modules exist.

## 1. Requirements

| # | Feedback | Action | Acceptance check | Status |
|---|---|---|---|---|
| F1 | Improve UI consistency, visual quality, usability | Define one set of shared UI rules (spacing, colours, buttons, empty/loading/error states, table style) and apply them page by page. Reuse the existing Tailwind classes (`card`, `btn-primary`, `input-field`). | Same components and states on every page; checked with a page-by-page review sheet. | TODO |
| F2 | Improve layout, navigation, hierarchy, responsiveness | Review sidebar/header grouping, page titles and primary actions; test at 360, 768, 1280 px. | No horizontal scroll; primary action visible without scrolling on each page; Playwright viewport checks for key pages. | TODO |
| F3 | Beginner-friendly guidance and explanations | Short "what is this" text per page, plain-language labels, tooltips for jargon (e.g. VM, RBAC, MAPE); extend the existing Learning panel rather than adding a new system. | A first-time user can finish the main journey (create VM → policy → cost → report) without outside help (test with 2–3 classmates). | TODO |
| F4 | Verify the real AI/ML implementation | Produce an **evidence note** per model (see section 2). Do not claim capabilities that are not in the code. | Each model has: purpose, algorithm, input data and source, training procedure (or "none/rule-based"), metrics, reason for choice, limitations. | TODO |
| F5 | Improve the final demonstration video | Script and rehearse; record at 1920×1080, browser zoom 110–125 %, large cursor, no notification popups; cover every module; add captions. | Text is readable at 720p playback; checklist of all modules shown; under the supervisor's time limit. | TODO |
| F6 | Professional presentation | Consistent slides/report, architecture and flow diagrams, traceability table, live-demo fallback (recorded video), rehearsed Q&A. | Dry run with supervisor feedback incorporated. | TODO |

## 2. F4 — AI/ML evidence checklist (verify, do not assume)

For every model/engine below, fill in the evidence note from the code and data, not from memory:

- Threat detector (`app/ai_models`, `/api/security/*`)
- Cost forecaster (`ai_models/cost_forecaster.py`, `/api/cost/forecast`)
- Wastage / optimization recommendations (`/api/cost/optimization`)
- Synthetic data generator (`ai_models/data_generator.py`)
- Learning recommendations / operational insights engines

Questions each note must answer: What algorithm is actually executed? Is it trained, and on which dataset (name, size, source, licence)? How was it evaluated (split, metric, result)? Why this model over alternatives? What happens when the model/data is unavailable (fallback)?

Observations from earlier work, **not yet verified** and to be confirmed or corrected in the audit:
- Cost forecast code contains a moving-average fallback (`fallback_forecast`); it must be stated clearly when this fallback is what runs.
- Threat analysis has a basic fallback (`basic_threat_analysis`) used when no detector is loaded.
- Wastage recommendations are explicit rules (IDLE / UNDERUTILIZED), i.e. rule-based, not ML.
- The data generator is statistical sampling (seeded noise around a dataset-derived baseline), i.e. simulation, not a learned model.

Rule: anything rule-based or simulated is described as such in the report, video and viva.

## 3. FUTURE FEATURE — Interactive Tutorial (final stage only)

**Timing:** implement only after **all 12 modules are complete**. Do not install a tour library or write tutorial code before then.

**Goal:** an optional guided tour for beginners that highlights each important control and explains it in plain language.

### Requirements
- Highlight and focus each important UI control (spotlight/overlay) with a short, beginner-friendly explanation of what the button does and when to use it.
- Controls: **Next, Back, Skip, End, Replay**; keyboard support (arrow keys, Esc) and screen-reader labels.
- Works across the relevant pages (multi-page tour: Dashboard → Resources → Security → Governance → Cost → Reports → etc.) and on desktop, tablet and mobile widths (popover repositions; mobile steps may target the menu button).
- Optional and non-blocking: offered on first login, never forced; "Don't show again" and a persistent "Take the tour" / Help entry; remember preference (per user, e.g. in user settings, with localStorage as fallback).
- Contextual help: "?" buttons on complex forms that start only that page's mini-tour.
- Graceful failure: if a target control is missing (role permissions, empty state, feature flag), skip that step or show a centered explanation instead of breaking; wait briefly for elements that appear in modals.
- Role-aware: viewers do not see steps for actions they cannot perform.
- Stable targets: add `data-tour="..."` attributes (not CSS classes) so UI restyling does not break the tour.
- Content lives in one data file (step id, page, target, title, text, role), easy to review for wording.

### Design references (concepts only — no branding or layout copying)
- **Driver.js** (https://driverjs.com/docs/configuration): framework-agnostic, small; useful concepts — `steps` with per-step popovers, configurable Next/Prev/Done labels, `allowClose`/overlay behaviour, `onDestroyed` reason (`done`/`close`/`escape`), `allowKeyboardControl`, `closeBtnLabel` for accessibility, `skipMissingElement` and `waitForElement` for missing/late targets.
- **React Joyride** (https://github.com/gilbarbara/react-joyride, docs at react-joyride.com): React-specific; README states React 16.8–19 support, MIT licence, focus trapping, keyboard navigation and ARIA, `steps` with `target` + `content`, and a `run` prop / hook `controls` for controlled tours. (The docs site was unreachable during this research; re-read step options, events and controlled-mode details before choosing.)
- **HEC / eServices portal guidance** (https://www.hec.gov.pk, https://eservices.hec.gov.pk): official pages and FAQs show the pattern of step-by-step applicant guidance (register → complete profile → upload documents → pay → submit) and plain-language FAQs. Only the *idea* of ordered, plain-language steps with a clear prerequisite per step is reused. Detailed HEC/PERN portal workflows were not verifiable from public search and are not copied.

### Decision (made at implementation time)
Choose between React Joyride (React-native API, already fits React 18) and Driver.js (lighter, DOM-based) after a small spike on one page; check licence, bundle size, a11y and multi-page behaviour. Add the dependency only then.

### Acceptance checks
- Tour completes, can be skipped at any step, ended, and replayed from Help.
- Preference persists across reload and devices of the same user.
- Playwright: tour start/next/back/skip on 2 pages at 360 px and 1280 px; missing-target step does not crash.
- Keyboard-only and screen-reader pass on one page.

## 4. Suggested order
1. F4 evidence audit (affects what the report and video may claim).
2. F1–F3 UI pass, page by page, with Playwright viewport checks.
3. Finish Modules 10–12.
4. Interactive tutorial (section 3).
5. F5 video and F6 presentation, recorded last so they match the final UI.
