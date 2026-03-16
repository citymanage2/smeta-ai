# smeta-ai

## What This Is

smeta-ai is a deployed AI-powered construction cost estimation service. Users upload construction documents (TZ, plans, existing estimates) and the service uses the Claude API to generate cost estimates, work item lists, Excel/PDF reports, and document comparisons. The service runs on Render with a FastAPI backend, React/TypeScript frontend, and PostgreSQL database.

## Core Value

A construction professional uploads documents and receives a ready-to-use cost estimate — the entire AI processing pipeline must work reliably end-to-end.

## Requirements

### Validated

- ✓ User authentication (login with role + password, JWT tokens) — existing
- ✓ File upload (PDF, Excel, images, XML, up to 20MB) — existing
- ✓ Async task creation with background processing — existing
- ✓ Task status polling with progress messages — existing
- ✓ Four task types: LIST_FROM_TZ, SMETA_FROM_LIST, SCAN_TO_EXCEL, COMPARE_PROJECT_SMETA — existing
- ✓ Result file generation (Excel/PDF output) — existing
- ✓ Result file download — existing
- ✓ Role-based routing (user vs admin) — existing (partial)

### Active

- [ ] **BUG-01**: Task creation resets to empty state after submission — polling endpoint returns 404, frontend treats it as failure and resets the form
- [ ] **BUG-02**: Page refresh / direct URL returns "Not Found" — SPA routing broken on Render static site deployment (_redirects fix committed but not working)
- [ ] **BUG-03**: Admin login displays "Пользователь" instead of "Администратор" — admin role not correctly identified or passed to frontend
- [ ] **FEAT-01**: Admin panel — paginated table of all requests with: date/time, uploaded filenames (re-downloadable), task type, result file (downloadable), full Claude conversation transcript
- [ ] **TEST-01**: Automated test suite (pytest) covering: auth, task creation, polling, result download, admin endpoints
- [ ] **TEST-02**: Manual E2E test checklist for post-deployment verification of all critical flows

### Out of Scope

- Multi-user accounts (username/email fields) — single user per role by design for now
- Task cancellation — not requested
- Result expiry / cleanup jobs — not requested
- Mobile app — web-first
- Real-time WebSocket updates — polling is sufficient

## Context

**Current deployment:** Render (static site for frontend, web service for backend). Frontend build output served from `frontend/dist/`. Backend runs as uvicorn on Render's web service.

**SPA routing issue:** The `_redirects` file needs to exist in the correct location for Render's static site to serve `index.html` for all routes. Previous fix commit may have placed it in the wrong directory or the file may not be included in the build output.

**Admin role bug:** Authentication uses role+password only (no username). The JWT token has a `role` field. Likely either the token creation doesn't set role to "admin", or the frontend auth store isn't reading the role field correctly.

**Polling bug:** Frontend polls `GET /tasks/{taskId}/status`. A 404 on this endpoint likely means either: (a) the task_id is not being passed correctly, (b) the route requires authentication but the token isn't being sent, or (c) a route definition mismatch.

**Admin panel data:** All necessary data is already stored in the database — `Task` model has `input_files` (JSON with filenames + base64 data), `task_type`, `chat_history` (JSON), `created_at`. `TaskResult` has the output file binary. The admin router (`backend/app/routers/admin.py`) already exists.

**Tech stack:** FastAPI + asyncpg/SQLAlchemy async, React 18 + TypeScript + Vite, PostgreSQL, Render deployment, Claude API (anthropic SDK).

## Constraints

- **Deployment**: Render static site + web service — must keep build and routing compatible
- **Database**: PostgreSQL on Render — no schema breaking changes without migration
- **Auth**: Keep existing JWT + role-based system — no overhaul of auth model
- **No downtime**: Fixes must be deployable without data loss or service interruption

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|----------|
| Admin panel as new route `/admin` | Route already exists in App.tsx, admin router in backend | — Pending |
| Paginated table for admin history | Simpler than cards, scales to many records | — Pending |
| pytest for backend tests | Already the standard for FastAPI | — Pending |
| Manual checklist alongside automated tests | Deployment verification requires human eyes | — Pending |

---
*Last updated: 2026-03-17 after initialization*
