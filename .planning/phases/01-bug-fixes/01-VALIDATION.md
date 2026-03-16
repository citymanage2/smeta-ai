---
phase: 1
slug: bug-fixes
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-17
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest |
| **Config file** | none — pytest default discovery |
| **Quick run command** | `cd backend && python -m pytest tests/ -x -q` |
| **Full suite command** | `cd backend && python -m pytest tests/ -v` |
| **Estimated runtime** | ~10 seconds |

---

## Sampling Rate

- **After every task commit:** Run `cd backend && python -m pytest tests/test_basic.py -x -q`
- **After every plan wave:** Run `cd backend && python -m pytest tests/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 1-01-01 | 01 | 0 | BUG-01 | unit | `cd backend && python -m pytest tests/test_bug01.py -x` | ❌ W0 | ⬜ pending |
| 1-01-02 | 01 | 0 | BUG-01 | integration | `cd backend && python -m pytest tests/test_bug01.py::test_poll_valid_task -x` | ❌ W0 | ⬜ pending |
| 1-01-03 | 01 | 1 | BUG-02 | smoke | `ls frontend/public/_redirects && echo OK` | ✅ exists | ⬜ pending |
| 1-01-04 | 01 | 1 | BUG-03 | unit | `cd backend && python -m pytest tests/test_bug03.py -x` | ❌ W0 | ⬜ pending |
| 1-01-05 | 01 | 1 | BUG-03 | unit | `cd backend && python -m pytest tests/test_bug03.py::test_password_update_on_startup -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `backend/tests/test_bug01.py` — stubs for BUG-01: task creation response shape, poll endpoint with valid task ID
- [ ] `backend/tests/test_bug03.py` — stubs for BUG-03: admin login returns role="admin", `_initialize_users` password update logic
- [ ] `backend/tests/conftest.py` — shared async fixtures (TestClient, test DB session) if not already present
- [ ] Verify `pytest-asyncio` installed: `cd backend && pip show pytest-asyncio`

*Existing `backend/tests/test_basic.py` covers baseline smoke tests.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Page refresh loads correct route | BUG-02 | Requires live Render deployment | 1. Deploy to Render 2. Navigate to `/task/create` 3. Press F5 4. Confirm page loads (not "Not Found") |
| Admin role indicator in UI | BUG-03 | Requires browser + auth flow | 1. Open app 2. Log in with admin password 3. Confirm header shows "Администратор" not "Пользователь" |
| Task creation polling in production | BUG-01 | Requires live backend + API routing | 1. Upload a file 2. Click "Создать задачу" 3. Confirm page transitions to status view 4. Confirm no 404 in network tab |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
