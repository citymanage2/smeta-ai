---
phase: 03-test-coverage
plan: 02
subsystem: testing
tags: [e2e, manual-testing, checklist, post-deployment, verification]

# Dependency graph
requires:
  - phase: 03-test-coverage
    provides: plan 01 backend test suite — established endpoint paths and expected API behavior
  - phase: 01-bug-fixes
    provides: all critical bugs fixed (BUG-01 API URL, BUG-02 SPA routing, BUG-03 admin role)
  - phase: 02-admin-panel
    provides: admin panel features (pagination, file downloads, chat transcript)
provides:
  - Manual E2E post-deployment verification checklist with 42 step-by-step test items
  - Coverage of all three phases' success criteria in a single runnable document
  - Sign-off table for tracking deployment verification
affects:
  - ci-cd
  - deployment
  - operations

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Checklist pattern: numbered sections per user role/flow, checkbox items with action + expected outcome"
    - "Verification sign-off table at the end of checklist for release gate tracking"

key-files:
  created:
    - backend/tests/E2E_CHECKLIST.md
  modified: []

key-decisions:
  - "10-section structure mirrors backend router organization (auth, tasks, results, admin) for easy traceability"
  - "Include exact API endpoint paths and JSON response shapes so tester can verify at the API level if UI is ambiguous"
  - "Cover BUG-03 admin role display explicitly with note about what regression it guards against"
  - "Include edge cases (mobile viewport, cross-browser, large file) in Section 10 for completeness"

patterns-established:
  - "E2E checklist pattern: Section per flow, checkbox per step, Action + Expected outcome for every item, Sign-off table"

requirements-completed: [TEST-02]

# Metrics
duration: 2min
completed: 2026-03-18
---

# Phase 3 Plan 02: Test Coverage Summary

**211-line manual E2E checklist with 42 verification steps across 10 sections covering every critical user flow, admin panel feature, and error scenario — ready for post-deployment sign-off**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-17T23:07:38Z
- **Completed:** 2026-03-17T23:09:18Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments
- Created `backend/tests/E2E_CHECKLIST.md` with 10 sections and 42 checkbox items, each with a specific action and expected outcome
- Covered all Phase 1 regression checks (BUG-01: API base URL, BUG-02: SPA routing on direct navigation, BUG-03: admin role display showing "Администратор")
- Covered all Phase 2 admin panel features (paginated task table, input file re-download, result file download, chat transcript expansion)
- Included exact API endpoint paths, error message text, and JSON response shapes for API-level verification

## Task Commits

Each task was committed atomically:

1. **Task 1: Create comprehensive manual E2E test checklist** - `7fac687` (docs)

**Plan metadata:** (docs commit — see below)

## Files Created/Modified
- `backend/tests/E2E_CHECKLIST.md` - 10-section manual E2E verification checklist with 42 numbered checkbox items, exact URLs, input values, expected outcomes, and sign-off table

## Decisions Made
- Structured sections to mirror backend router organization (auth → tasks → results → admin) so developers can trace each checklist item back to the corresponding endpoint
- Included exact error message strings (e.g., "Неверный пароль", "Формат .gsn не поддерживается") so testers can confirm error handling without ambiguity
- Added API curl examples in Section 6.4 so testers who prefer API verification over UI can do so in parallel
- Section 10 covers cross-browser, mobile, large file, and incognito scenarios that automated tests cannot catch

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required. The checklist itself is the deliverable.

## Next Phase Readiness
- E2E checklist is complete and available for use after any deployment
- To use: open `backend/tests/E2E_CHECKLIST.md`, substitute `{BACKEND_URL}` and `{FRONTEND_URL}` with actual deployed URLs, follow steps top to bottom, check off each item
- Phase 3 (test coverage) is now complete: automated backend tests (plan 01) + manual E2E checklist (plan 02)

---
*Phase: 03-test-coverage*
*Completed: 2026-03-18*

## Self-Check: PASSED

- `backend/tests/E2E_CHECKLIST.md` exists: YES (211 lines, 42 checkboxes)
- Task commit `7fac687` verified in git log
- All acceptance criteria met: sections present, Администратор appears, /health appears, Sign-Off table present
