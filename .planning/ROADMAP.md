# Roadmap: smeta-ai

## Overview

The service is deployed and the core AI pipeline works, but three production bugs are blocking reliable use. This roadmap fixes those bugs, completes the admin panel feature, then locks in quality with automated and manual tests. Three phases deliver a fully functional, verifiable service.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Bug Fixes** - Restore correct behavior for task polling, SPA routing, and admin role display
- [ ] **Phase 2: Admin Panel** - Deliver complete admin request history with file re-download and conversation transcripts
- [ ] **Phase 3: Test Coverage** - Automated pytest suite and manual E2E checklist covering all critical flows

## Phase Details

### Phase 1: Bug Fixes
**Goal**: All three broken production behaviors are corrected and the service works as designed
**Depends on**: Nothing (first phase)
**Requirements**: BUG-01, BUG-02, BUG-03
**Success Criteria** (what must be TRUE):
  1. After submitting a task, the user sees polling progress — the form does not reset to empty state and no 404 appears in the network log
  2. Refreshing the page or navigating directly to any route (e.g., `/admin`) loads the correct page instead of returning "Not Found"
  3. After logging in as admin, the UI displays "Администратор" in the role indicator, not "Пользователь"
**Plans**: TBD

### Phase 2: Admin Panel
**Goal**: Admin can inspect the full history of all requests with access to every associated file and conversation
**Depends on**: Phase 1
**Requirements**: ADMIN-01, ADMIN-02, ADMIN-03, ADMIN-04
**Success Criteria** (what must be TRUE):
  1. Admin sees a paginated table at `/admin` listing all requests with date/time, task type, and status — oldest and newest records both visible via pagination
  2. Admin can click to re-download any original file uploaded by a user directly from the history table
  3. Admin can download the generated result file (Excel/PDF) for any completed request from the history table
  4. Admin can expand a row to read the full Claude conversation transcript inline without leaving the page
**Plans**: TBD

### Phase 3: Test Coverage
**Goal**: All critical flows are covered by automated tests and a verified manual checklist exists for post-deployment use
**Depends on**: Phase 2
**Requirements**: TEST-01, TEST-02, TEST-03
**Success Criteria** (what must be TRUE):
  1. Running `pytest` from the backend directory executes tests for: valid/invalid login, role verification, task creation, task status polling, result download, and admin panel endpoints — all pass against a test database
  2. A manual E2E checklist document exists that a developer can follow step-by-step to verify every critical user flow after deployment
  3. Any additional bugs discovered during test execution are fixed before the phase is marked complete
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Bug Fixes | 0/? | Not started | - |
| 2. Admin Panel | 0/? | Not started | - |
| 3. Test Coverage | 0/? | Not started | - |
