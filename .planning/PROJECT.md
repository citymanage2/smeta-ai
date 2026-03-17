# smeta-ai

## What This Is

smeta-ai is a deployed AI-powered construction cost estimation service. Users upload construction documents (TZ, plans, existing estimates) and the service uses the Claude API to generate cost estimates, work item lists, Excel/PDF reports, and document comparisons. The service runs on Render with a FastAPI backend, React/TypeScript frontend, and PostgreSQL database.

v1.0 shipped with all three critical production bugs fixed, a complete admin panel for request history inspection, and a 28-test automated suite plus a 42-step manual E2E checklist.

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
- ✓ Role-based routing (user vs admin) — existing
- ✓ BUG-01: Task creation no longer resets form on polling 404 — v1.0
- ✓ BUG-02: SPA routing works on Render static site (page refresh + direct URL) — v1.0
- ✓ BUG-03: Admin login shows "Администратор" (password hash sync on startup) — v1.0
- ✓ ADMIN-01: Admin paginated table of all requests with date/time, task type, status — v1.0 (pre-GSD)
- ✓ ADMIN-02: Admin can re-download original files from request history — v1.0 (pre-GSD)
- ✓ ADMIN-03: Admin can download result files from request history — v1.0 (pre-GSD)
- ✓ ADMIN-04: Admin can view full Claude conversation transcript inline — v1.0 (pre-GSD)
- ✓ TEST-01: pytest suite covering auth, tasks, results, admin endpoints — v1.0
- ✓ TEST-02: Manual E2E checklist for post-deployment verification — v1.0
- ✓ TEST-03: Additional bugs discovered during testing fixed — v1.0

### Active

(None — next milestone requirements to be defined via `/gsd:new-milestone`)

### Out of Scope

| Feature | Reason |
|---------|--------|
| Multi-user accounts (username/email) | Single user per role by design for v1 |
| Real-time WebSocket updates | Polling is sufficient |
| Mobile app | Web-first |
| Task cancellation | Not requested for v1 |
| OAuth / social login | Not needed |
| Offline mode | Real-time pipeline is core value |

## Context

**Shipped v1.0** on 2026-03-18. ~16 files modified across 4 plans.

**Tech stack:** FastAPI + SQLAlchemy async (PostgreSQL in prod, SQLite in tests), React 18 + TypeScript + Vite, Render deployment, Claude API (anthropic SDK), pytest + httpx + aiosqlite for testing.

**Deployment:** Render static site (frontend) + web service (backend). `VITE_API_BASE_URL` must be set in Render dashboard for production API routing to work.

**Known tech debt from v1.0:**
- `client.ts` fallback URL is hardcoded `'https://smeta-ai-backend.onrender.com'` — docs said `/api` but code differs. Local dev without `VITE_API_BASE_URL` hits production backend.
- BUG-03 stale-hash repair branch in `_initialize_users()` has no automated regression test.
- `_get_user_token()` helper in `test_admin.py` bypasses fixture graph — fragile if `create_access_token` interface changes.
- Nyquist VALIDATION.md files incomplete/missing for Phases 1 and 3.

## Constraints

- **Deployment**: Render static site + web service — must keep build and routing compatible
- **Database**: PostgreSQL on Render — no schema breaking changes without migration
- **Auth**: Keep existing JWT + role-based system — no overhaul of auth model
- **No downtime**: Changes must be deployable without data loss or service interruption

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| VITE_API_BASE_URL env var for API routing | Simpler than Render proxy; explicit, no hidden indirection | ✓ Good — works in prod |
| task_id guard in TaskCreate.tsx before navigate() | Fail fast with visible error rather than silent redirect loop | ✓ Good |
| Password hash sync on startup (lifespan) | Self-healing on each deploy; simpler than migration script | ✓ Good |
| String(36) instead of postgresql.UUID in models | SQLite test compatibility; identical storage semantics in PostgreSQL | ✓ Good |
| Optional[X] instead of X\|None annotations | Python 3.9 system compat; SQLAlchemy eval() rejects PEP 604 syntax | ✓ Good — backward compatible |
| Session-scoped table creation + function-scoped seed data | Balance of speed and isolation without per-test schema recreation | ✓ Good |
| 10-section E2E checklist mirroring backend router organization | Traceability — each checklist item maps to a router | ✓ Good |
| Admin panel built outside GSD pipeline | Pre-existing or built alongside Phase 1 outside GSD | ⚠️ Revisit — no formal verification artifacts |

---
*Last updated: 2026-03-18 after v1.0 milestone*
