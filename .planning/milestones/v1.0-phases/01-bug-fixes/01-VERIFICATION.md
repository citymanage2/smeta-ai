---
phase: 01-bug-fixes
verified: 2026-03-17T00:00:00Z
status: human_needed
score: 5/5 must-haves verified
re_verification: false
human_verification:
  - test: "Deploy to Render with VITE_API_BASE_URL set and submit a task"
    expected: "User is redirected to /task/{uuid}/status and sees polling progress; the form does not reset and no 404 appears in the network log"
    why_human: "BUG-01 fix is code-complete but requires VITE_API_BASE_URL to be set in the Render dashboard env vars before the fix activates in production. Cannot verify env var presence or production routing programmatically."
  - test: "Navigate to /admin or /task/create directly (by typing the URL), then refresh the page"
    expected: "The correct page loads instead of returning 'Not Found' (404)"
    why_human: "BUG-02 fix (_redirects + render.yaml rewrite rule) is code-complete and verified correct locally, but activation requires a fresh Render deploy. Static hosting routing behaviour cannot be verified without a live deployment."
  - test: "Log in with the current ADMIN_PASSWORD value from the Render environment after the next deploy"
    expected: "The header role badge displays 'Администратор', not 'Пользователь'; the user is redirected to /admin"
    why_human: "BUG-03 fix runs at startup against the live PostgreSQL database. The hash-sync logic is code-complete and verified by inspection, but correctness against a real stale-hash database row can only be confirmed after the next Render deploy runs _initialize_users against production data."
---

# Phase 1: Bug Fixes — Verification Report

**Phase Goal:** All three broken production behaviors are corrected and the service works as designed
**Verified:** 2026-03-17
**Status:** human_needed — all automated checks passed; three items require live-deployment confirmation
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| #  | Truth | Status | Evidence |
|----|-------|--------|----------|
| 1  | After submitting a task, user navigates to /task/{uuid}/status and sees polling progress — no redirect back to /task/create | VERIFIED (code) / HUMAN for production | Guard `if (!task.task_id)` at line 46 of TaskCreate.tsx; `navigate(\`/task/${task.task_id}/status\`)` at line 50; VITE_API_BASE_URL fallback in client.ts line 4 |
| 2  | API calls from the frontend reach the backend in both development (Vite proxy) and production (direct URL) | VERIFIED (code) / HUMAN for production | `baseURL: import.meta.env.VITE_API_BASE_URL \|\| '/api'` in client.ts line 4; request interceptor attaches Bearer token; production requires VITE_API_BASE_URL set in Render dashboard |
| 3  | Page refresh on any route loads the correct page instead of 'Not Found' | VERIFIED (code) / HUMAN for production | `frontend/public/_redirects` contains `/* /index.html 200` (ASCII, no BOM); `render.yaml` has `type: rewrite` / `destination: /index.html`; requires fresh Render deploy |
| 4  | After logging in as admin, the UI displays 'Администратор' in the role badge | VERIFIED (code) / HUMAN for production | `_initialize_users` in main.py lines 53-55 re-hashes on mismatch; auth.py login returns `role="admin"` when verify_password succeeds; Layout.tsx line 61 renders 'Администратор' when `role === 'admin'` |
| 5  | Password hashes in the database are updated on every application startup to match current environment variables | VERIFIED | `else` branch in `_initialize_users` (main.py lines 51-55): calls `verify_password(password, existing.password_hash)` and reassigns `existing.password_hash = hash_password(password)` when mismatch; covered by lifespan call at line 66 |

**Score:** 5/5 truths verified at code level; 3/5 require live deployment to confirm end-to-end

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `frontend/src/api/client.ts` | Axios client with env-var-based API base URL | VERIFIED | Line 4: `baseURL: import.meta.env.VITE_API_BASE_URL \|\| '/api'`; request interceptor (localStorage token) and 401 response interceptor both intact |
| `frontend/src/pages/TaskCreate.tsx` | Guard against undefined task_id before navigation | VERIFIED | Lines 46-49: `if (!task.task_id)` sets Russian error message and returns; line 50: `navigate(\`/task/${task.task_id}/status\`)` only reached when task_id is truthy |
| `frontend/public/_redirects` | SPA routing rewrite rule for Render static site | VERIFIED | Contains exactly `/* /index.html 200`; file encoding is ASCII text with no BOM or Windows line endings |
| `backend/app/main.py` | `_initialize_users` function that updates password hashes for existing users | VERIFIED | Lines 33-57: full implementation with `verify_password` check and `hash_password` update in else branch |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `frontend/src/api/client.ts` | backend API | `baseURL` from `VITE_API_BASE_URL` env var or `/api` fallback | VERIFIED | Pattern `VITE_API_BASE_URL` present at line 4; `import.meta.env.VITE_API_BASE_URL \|\| '/api'` |
| `frontend/src/pages/TaskCreate.tsx` | `frontend/src/pages/TaskStatus.tsx` | `navigate` with validated `task_id` | VERIFIED | `task.task_id` guard at line 46; navigate call at line 50 uses the validated value |
| `backend/app/main.py` | `backend/app/utils/auth.py` | `verify_password` + `hash_password` calls in `_initialize_users` | VERIFIED | Line 14 imports both; `verify_password(password, existing.password_hash)` at line 53; `hash_password(password)` at line 54 |
| `backend/app/routers/auth.py` | `backend/app/models/user.py` | login endpoint reads user by role and verifies password | VERIFIED | Line 44: `verify_password(body.password, user.password_hash)`; returns `LoginResponse(role=role)` which frontend auth.ts stores in localStorage and Zustand |

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| BUG-01 | 01-01-PLAN.md | Polling endpoint 404 no longer causes the task creation form to reset | SATISFIED | `VITE_API_BASE_URL` in client.ts; `task_id` guard in TaskCreate.tsx; commits 8bd9b92 |
| BUG-02 | 01-01-PLAN.md | Page refresh and direct URL navigation works correctly on all routes | SATISFIED (deployment-gated) | `_redirects` correct (ASCII, `/* /index.html 200`); `render.yaml` has rewrite rule; activation requires Render deploy |
| BUG-03 | 01-02-PLAN.md | Admin login displays "Администратор" in the UI | SATISFIED (deployment-gated) | `_initialize_users` else-branch re-hashes stale hashes; auth.py returns `role="admin"` on match; Layout.tsx renders correct label; commit 9f09780 |

All three requirements claimed in PLAN frontmatter are accounted for. No requirements mapped to Phase 1 in REQUIREMENTS.md are orphaned.

---

## Anti-Patterns Found

No anti-patterns detected in the files modified by this phase.

Checks performed on `frontend/src/api/client.ts`, `frontend/src/pages/TaskCreate.tsx`, `backend/app/main.py`:

- No TODO/FIXME/HACK/PLACEHOLDER comments
- No stub returns (`return null`, `return {}`, `return []`)
- No empty handlers (`() => {}`, `() => console.log(...)`)
- No form handlers that only call `preventDefault()` without further action
- No API queries with static return values that bypass the result

---

## Human Verification Required

### 1. BUG-01: Task Creation Polling in Production

**Test:** Set `VITE_API_BASE_URL=https://smeta-ai-backend.onrender.com` in the Render frontend static site's Environment Variables, trigger a new deploy, then log in as a regular user and submit a task with a file.

**Expected:** The user is redirected to `/task/{uuid}/status` and sees a live polling progress indicator. No 404 appears in the browser network tab. The task creation form does not reappear.

**Why human:** The code fix is verified but the VITE_API_BASE_URL variable must be present in the Render build environment for `import.meta.env.VITE_API_BASE_URL` to resolve to anything other than `undefined` at bundle time. This cannot be confirmed without access to the Render dashboard and a live build.

---

### 2. BUG-02: SPA Routing on Page Refresh

**Test:** After the next Render deploy (to pick up the `_redirects` file), open the app and navigate to `/admin` or `/task/create` via the address bar or by pressing F5 on an already-loaded route.

**Expected:** The correct React page renders. No "Not Found" or 404 page appears.

**Why human:** The `_redirects` file and `render.yaml` rewrite rule are both verified correct in the repository. However the fix is deployment-gated — the previous Render build may be serving a stale static bundle that doesn't include the file. Only a live deploy confirms the fix is active.

---

### 3. BUG-03: Admin Role Display After Deploy

**Test:** After pushing commit 9f09780 and triggering a Render backend redeploy, log in using the value of `ADMIN_PASSWORD` currently set in the Render backend service's environment variables.

**Expected:** The header role badge displays "Администратор". The user is redirected to the `/admin` page, not `/task/create`.

**Why human:** The `_initialize_users` hash-sync logic runs against the live PostgreSQL database at startup. Its correctness when the stored hash is genuinely stale can only be confirmed in the live environment after the deploy completes. The code logic is verified correct by inspection, but the database state at the time of the next deploy determines whether the update branch is triggered.

---

## Gaps Summary

No automated gaps found. All code-level must-haves are satisfied:

- All four required artifacts exist, are substantive, and are wired into the application flow.
- All four key links are verified present in source code.
- All three requirement IDs (BUG-01, BUG-02, BUG-03) are covered by the implemented plans and committed code.
- No orphaned requirements exist for Phase 1.

The three human verification items are deployment-gated confirmations, not code deficiencies. The phase goal is achieved at the code level; production confirmation requires a Render deploy with the documented environment variable in place.

---

_Verified: 2026-03-17_
_Verifier: Claude (gsd-verifier)_
