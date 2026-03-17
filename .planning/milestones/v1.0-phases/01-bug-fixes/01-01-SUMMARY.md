---
phase: 01-bug-fixes
plan: 01
subsystem: api
tags: [axios, react, vite, env-vars, spa-routing, render]

# Dependency graph
requires: []
provides:
  - "Axios client reads VITE_API_BASE_URL env var so production frontend calls the correct backend domain"
  - "TaskCreate.tsx guards against undefined task_id before navigation preventing redirect loop"
  - "SPA routing verified correct in _redirects and render.yaml"
affects: [02-bug-fixes, 03-test-coverage]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Env-var-first API base URL: import.meta.env.VITE_API_BASE_URL || '/api' for dev/prod compatibility"
    - "Defensive navigation guard: check task_id truthy before calling navigate() to avoid undefined routes"

key-files:
  created: []
  modified:
    - frontend/src/api/client.ts
    - frontend/src/pages/TaskCreate.tsx

key-decisions:
  - "Use VITE_API_BASE_URL with /api fallback — dev uses Vite proxy, production sets full backend URL in Render dashboard"
  - "Guard task_id before navigate rather than relying solely on TaskStatus.tsx redirect — fail fast with a visible error message"
  - "BUG-02 is code-complete; fix requires a fresh Render deploy to take effect (not a code change)"

patterns-established:
  - "Env-var API URL: always use import.meta.env.VITE_API_BASE_URL || '/api' in client.ts for cross-env routing"
  - "Navigation safety: validate all route params before calling navigate() in form submit handlers"

requirements-completed: [BUG-01, BUG-02]

# Metrics
duration: 6min
completed: 2026-03-17
---

# Phase 1 Plan 01: Bug Fixes - API URL + SPA Routing Summary

**Axios client now uses VITE_API_BASE_URL env var for production backend routing; TaskCreate.tsx guards against undefined task_id before navigation; SPA _redirects and render.yaml verified clean.**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-03-16T23:52:40Z
- **Completed:** 2026-03-17T00:00:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Fixed BUG-01 root cause: production API calls now route to the correct backend domain via VITE_API_BASE_URL
- Added defensive task_id guard in TaskCreate.tsx — user sees an error instead of a silent redirect loop when task_id is undefined
- Verified BUG-02 SPA routing configuration is correct (ASCII clean, no BOM, proper syntax); documented that a fresh Render deploy is required to activate the already-committed fix

## Task Commits

Each task was committed atomically:

1. **Task 1: Fix API base URL for production and add task_id safety guard** - `8bd9b92` (fix)
2. **Task 2: Verify SPA routing configuration** - no code changes (verification only)

**Plan metadata:** (docs commit — see below)

## Files Created/Modified
- `frontend/src/api/client.ts` - Changed `baseURL: '/api'` to `baseURL: import.meta.env.VITE_API_BASE_URL || '/api'`
- `frontend/src/pages/TaskCreate.tsx` - Added `if (!task.task_id)` guard with Russian error message before `navigate()`

## Decisions Made
- VITE_API_BASE_URL pattern chosen over configuring a Render proxy — simpler, explicit, no hidden indirection. The variable must be set in the Render dashboard under the frontend static site's environment variables for the production build.
- Guard placed in TaskCreate.tsx rather than only in TaskStatus.tsx — provides immediate feedback at the point of failure rather than a confusing redirect.
- BUG-02 requires no code change; the `_redirects` file (ASCII, Unix line endings, correct syntax) and `render.yaml` rewrite rule are already correct. The fix is deployment-gated.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

**VITE_API_BASE_URL must be set in Render dashboard for BUG-01 fix to take effect in production.**

Steps:
1. In the Render dashboard, open the `smeta-ai-frontend` static site
2. Go to Environment > Environment Variables
3. Add: `VITE_API_BASE_URL` = `https://smeta-ai-backend.onrender.com` (verify exact backend URL in the backend service settings)
4. Trigger a new deploy (or it will auto-deploy on next push)

**For BUG-02 (SPA routing):** Push these commits to trigger a Render rebuild. The `_redirects` file and `render.yaml` rewrite rule are already correct — the fix just needs a fresh deploy.

## Next Phase Readiness
- BUG-01 and BUG-02 fixes are code-complete; production activation requires: (a) setting VITE_API_BASE_URL in Render dashboard, (b) pushing commits to trigger Render rebuild
- Ready to proceed to Plan 02 (BUG-03: admin role)

## Self-Check: PASSED

- frontend/src/api/client.ts: FOUND
- frontend/src/pages/TaskCreate.tsx: FOUND
- .planning/phases/01-bug-fixes/01-01-SUMMARY.md: FOUND
- commit 8bd9b92: FOUND

---
*Phase: 01-bug-fixes*
*Completed: 2026-03-17*
