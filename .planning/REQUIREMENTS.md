# Requirements: smeta-ai

**Defined:** 2026-03-17
**Core Value:** A construction professional uploads documents and receives a ready-to-use cost estimate — the entire AI processing pipeline must work reliably end-to-end.

## v1 Requirements

### Bug Fixes

- [x] **BUG-01**: Polling endpoint 404 no longer causes the task creation form to reset to empty state
- [x] **BUG-02**: Page refresh and direct URL navigation works correctly on all routes in Render static site deployment
- [ ] **BUG-03**: Admin login displays "Администратор" in the UI (not "Пользователь")

### Admin Panel

- [ ] **ADMIN-01**: Admin can view paginated table of all requests showing date/time, task type, and status
- [ ] **ADMIN-02**: Admin can re-download any original file uploaded by the user from request history
- [ ] **ADMIN-03**: Admin can download the generated result file (Excel/PDF) from request history
- [ ] **ADMIN-04**: Admin can view the full Claude conversation transcript for each request (expandable inline in the table)

### Testing

- [ ] **TEST-01**: pytest suite covers: authentication (valid/invalid login, role verification), task creation, task status polling, result download, and admin panel endpoints
- [ ] **TEST-02**: Manual E2E test checklist documents step-by-step verification of all critical flows for post-deployment use
- [ ] **TEST-03**: Additional bugs discovered during testing are identified and fixed

## v2 Requirements

### Audit & Security

- **SEC-01**: Rate limiting on auth endpoints (prevent brute force)
- **SEC-02**: User isolation — verify task ownership before allowing result download
- **SEC-03**: HttpOnly cookie tokens instead of localStorage

### UX Improvements

- **UX-01**: Task retry button for failed tasks
- **UX-02**: Admin panel date range filter and search
- **UX-03**: Task cancellation for long-running tasks

### Infrastructure

- **INFRA-01**: File storage off-database (S3 or filesystem) — current base64 in DB doesn't scale
- **INFRA-02**: Result file expiry / cleanup job

## Out of Scope

| Feature | Reason |
|---------|--------|
| Multi-user accounts (username/email) | Single user per role by design for v1 |
| Real-time WebSocket updates | Polling is sufficient |
| Mobile app | Web-first |
| Task cancellation | Not requested for v1 |
| OAuth / social login | Not needed |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| BUG-01 | Phase 1 | Complete (plan 01-01) |
| BUG-02 | Phase 1 | Complete (plan 01-01) |
| BUG-03 | Phase 1 | Pending |
| ADMIN-01 | Phase 2 | Pending |
| ADMIN-02 | Phase 2 | Pending |
| ADMIN-03 | Phase 2 | Pending |
| ADMIN-04 | Phase 2 | Pending |
| TEST-01 | Phase 3 | Pending |
| TEST-02 | Phase 3 | Pending |
| TEST-03 | Phase 3 | Pending |

**Coverage:**
- v1 requirements: 10 total
- Mapped to phases: 10
- Unmapped: 0 ✓

---
*Requirements defined: 2026-03-17*
*Last updated: 2026-03-17 after plan 01-01 completion*
