# Milestones

## v1.0 MVP (Shipped: 2026-03-18)

**Phases completed:** 2 phases via GSD (Phases 1 & 3), 4 plans, 7 tasks
**Files modified:** 16 | **Timeline:** 2026-03-17 → 2026-03-18

**Key accomplishments:**
1. Fixed production API routing via `VITE_API_BASE_URL` env var; added `task_id` guard before navigation (BUG-01, BUG-02)
2. Fixed stale admin password hash on startup — admin login now correctly shows "Администратор" (BUG-03)
3. Admin panel fully implemented (pre-GSD): paginated task table, file re-downloads, result downloads, inline chat transcripts (ADMIN-01–04)
4. 28-test async pytest suite via httpx + in-memory SQLite, zero external services needed (TEST-01, TEST-03)
5. 42-step manual E2E checklist covering all critical flows across 10 sections (TEST-02)
6. Fixed Python 3.9 type annotation compatibility across 5 production model/service files (side effect of test phase)

### Known Gaps

ADMIN-01 through ADMIN-04 are code-complete and test-covered, but Phase 2 was never executed through GSD — no PLAN/SUMMARY/VERIFICATION artifacts exist:

- `ADMIN-01`: Admin paginated task table — `Admin.tsx` + `admin.py`, tested in `test_admin.py`
- `ADMIN-02`: Admin re-download original files — `GET /admin/tasks/{id}/download-input/{index}` tested
- `ADMIN-03`: Admin download result files — `downloadResult()` → `GET /results/{file_id}/download` tested
- `ADMIN-04`: Admin view chat transcript — `Admin.tsx` renders `chat_history`, tested in `test_admin_get_task_detail`

---

