# Retrospective: smeta-ai

---

## Milestone: v1.0 — MVP

**Shipped:** 2026-03-18
**Phases:** 2 via GSD (1 & 3) + 1 pre-GSD (Admin Panel) | **Plans:** 4

### What Was Built

- API base URL fix via env var + task_id navigation guard (BUG-01, BUG-02)
- Admin password hash sync on startup (BUG-03)
- Admin panel: paginated table, file re-downloads, result downloads, chat transcripts (ADMIN-01–04, pre-GSD)
- 28-test async pytest suite with in-memory SQLite, zero external dependencies
- 42-step manual E2E checklist across 10 sections

### What Worked

- **Short plans execute fast**: All 4 plans completed in 2–8 minutes each. Focused scope kept execution clean.
- **In-memory SQLite strategy**: Using `aiosqlite` + dependency injection override let tests run anywhere without infrastructure — fast iteration.
- **Bug fix before testing**: Fixing production bugs first (Phase 1) gave the test suite a stable target.
- **Audit surfaced hidden context**: The milestone audit discovered Phase 2 was pre-built — without it, the gap would have been invisible at archive time.

### What Was Inefficient

- **Phase 2 skipped GSD entirely**: Admin panel was built outside the pipeline, leaving 4 requirements formally unverified. No PLAN, SUMMARY, or VERIFICATION artifacts were ever created. This created traceability debt that had to be acknowledged at milestone close.
- **Nyquist compliance never reached**: VALIDATION.md files were planned but never completed for either phase. Wave 0 test stubs were drafted but not created.
- **`client.ts` fallback diverged from docs**: Phase 1 documented `/api` as the fallback but the actual committed code uses the hardcoded production URL. Planning doc inaccuracy went unnoticed until the audit.

### Patterns Established

- `VITE_API_BASE_URL || '/api'` pattern for cross-env frontend API routing
- Startup hash-sync pattern: `verify_password` check before re-hashing in `_initialize_users`
- `String(36)` instead of `postgresql.UUID` for SQLite-compatible test models
- `Optional[X]` instead of `X | None` for Python 3.9 SQLAlchemy compatibility
- Session-scoped schema + function-scoped seed data for test isolation without overhead

### Key Lessons

1. **Run every phase through GSD** — even when code already exists. Pre-built features need retroactive PLAN/SUMMARY/VERIFICATION or they become known gaps at milestone close.
2. **Validate docs match code at plan close** — the `client.ts` discrepancy would have been caught immediately if the executor had diffed the committed code against the plan.
3. **Nyquist VALIDATION.md should be created at plan start**, not deferred. Drafting it without running Wave 0 provides no protection.

### Cost Observations

- Sessions: ~4 (Phase 1 plans, Phase 3 plans)
- All plans completed in under 10 minutes each
- Notable: test infrastructure (Phase 3 plan 01) was the most complex plan at 8 min, creating 6 new files and fixing 5 production files

---

## Cross-Milestone Trends

| Milestone | Phases | Plans | Avg Plan Duration | Nyquist Compliant |
|-----------|--------|-------|------------------|-------------------|
| v1.0 MVP | 2 (GSD) | 4 | ~6 min | No |
