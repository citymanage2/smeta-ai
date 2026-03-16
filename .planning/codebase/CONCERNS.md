# Codebase Concerns

**Analysis Date:** 2026-03-17

## Security Considerations

**Hardcoded Default Credentials:**
- Issue: Default passwords stored in plain text in `app/config.py` (USER_PASSWORD="user123", ADMIN_PASSWORD="admin123") and duplicated in environment variable defaults
- Files: `backend/app/config.py` (lines 12-13), `backend/app/main.py` (lines 36, 56)
- Impact: Anyone with code access can log in. No protection in production without environment override.
- Fix approach: Remove defaults entirely, require explicit environment variables at startup. Fail fast if missing. Document secure password generation process.

**Weak JWT Secret Default:**
- Issue: JWT_SECRET defaults to "changeme-use-strong-secret-in-production" (line 9 in `backend/app/config.py`)
- Files: `backend/app/config.py`, `backend/app/utils/auth.py` (line 31)
- Impact: If deployed without override, tokens are trivially forgeable
- Fix approach: Generate random secret on first startup if not provided, store in secure location. Validate at startup that secret is strong (>32 chars).

**No Rate Limiting on Auth Endpoints:**
- Issue: Login endpoint (`backend/app/routers/auth.py`, lines 27-57) has no rate limiting despite slowapi being configured
- Files: `backend/app/routers/auth.py`, `backend/app/main.py` (lines 30, 84-87)
- Impact: Brute force attacks possible
- Fix approach: Add `@limiter.limit("5/minute")` to login endpoint, log failed attempts with IP tracking

**Insufficient User Isolation:**
- Issue: No task ownership verification - results router only checks task exists, not user ownership
- Files: `backend/app/routers/results.py` (lines 26-54, 57-89) - missing user_id from Task model
- Impact: Any authenticated user can download any other user's results
- Fix approach: Add user_id to Task model, verify ownership in download_result and list_task_results endpoints

**Authentication via Password Only:**
- Issue: No username field - authentication uses role + password only. Assumes single user per role.
- Files: `backend/app/routers/auth.py` (lines 40-51), `backend/app/models/user.py`
- Impact: Multi-user scenarios impossible, password sharing unavoidable, audit trail impossible
- Fix approach: Add username/email field to User model, update login flow to accept (username, password), migrate task ownership to username

**localStorage Token Exposure:**
- Issue: JWT tokens stored in localStorage, accessible to XSS
- Files: `frontend/src/stores/auth.ts` (lines 13-14, 32-33), `frontend/src/api/client.ts` (line 13)
- Impact: XSS attacks can steal tokens
- Fix approach: Use httpOnly cookies instead of localStorage. Remove manual token management from client code.

---

## Tech Debt

**Monolithic Task Processor:**
- Issue: `backend/app/services/task_processor.py` (506 lines) handles all task types - LIST_FROM_TZ, SMETA_FROM_LIST, SCAN_TO_EXCEL, COMPARE_PROJECT_SMETA
- Files: `backend/app/services/task_processor.py` (lines 320-367 route dispatch)
- Impact: Adding new task type requires modifying core logic. Difficult to test individual flows. Error handling is global.
- Fix approach: Split into strategy pattern - TaskHandler base class + specialized handlers (ListHandler, SmetaHandler, etc) in separate files. Register handlers in dict.

**Large JSON Parsing Method:**
- Issue: `_parse_json_response` (lines 300-318) uses regex fallback that's fragile
- Files: `backend/app/services/task_processor.py`
- Impact: Claude responses with nested JSON fail. Markdown blocks cause silent failures.
- Fix approach: Use dedicated JSON extraction library (json5) or improve regex to handle nested braces: `\{(?:[^{}]|(?:\{[^{}]*\}))*\}`

**File Data Stored as Base64 in Database:**
- Issue: `input_file_data` in Task model stores base64-encoded file contents (up to 20MB per file)
- Files: `backend/app/models/task.py` (line 22), `backend/app/routers/tasks.py` (lines 145-151)
- Impact: Database bloat, slow queries, memory issues. Task startup loads entire file into memory.
- Fix approach: Store files in separate storage (S3, filesystem with cleanup). Keep only file metadata and path in Task.

**Result Files Never Cleaned Up:**
- Issue: `TaskResult` records with `file_data` (LargeBinary, line 20 in `backend/app/models/result.py`) accumulate indefinitely
- Files: `backend/app/models/result.py`, `backend/app/services/task_processor.py` (lines 242-250)
- Impact: Disk fills up over time. No retention policy.
- Fix approach: Add `expires_at` column to TaskResult. Implement cleanup job to delete expired records and cascade-delete old tasks.

**Global State in Price Service:**
- Issue: `_works_cache`, `_materials_cache`, `_cache_loaded` are module-level globals (lines 15-17 in `backend/app/services/price_service.py`)
- Files: `backend/app/services/price_service.py`
- Impact: Cache never refreshes. Stale prices during long-running server. Not thread-safe for updates.
- Fix approach: Make cache expiring (TTL=1 hour). Load in background task. Use thread-safe data structure or async lock.

**Blocking XML Parsing in Async Code:**
- Issue: `parse_file` uses synchronous XML parsing (ElementTree) in async context
- Files: `backend/app/utils/file_parser.py` (lines 47, 115-136)
- Impact: Large XML files block event loop, freezing other requests
- Fix approach: Move file parsing to thread pool using `asyncio.run_in_executor()` or use async XML library

**hardcoded System Prompts:**
- Issue: All Claude system prompts are hardcoded strings in `task_processor.py` (lines 22-211)
- Files: `backend/app/services/task_processor.py`
- Impact: Can't update without redeploying. No A/B testing capability.
- Fix approach: Move prompts to database or config file. Load at startup. Add versioning.

---

## Performance Bottlenecks

**Price Service Semantic Search Inefficiency:**
- Issue: `_semantic_match_work` and `_semantic_match_material` (lines 45-119) call Claude for EVERY unmatched item in smeta generation
- Files: `backend/app/services/price_service.py`
- Impact: If 100 items have no exact match, 100 Claude API calls. ~5 seconds per call = 500+ seconds for single task
- Fix approach: Batch semantic search - collect all unmatched names, search once. Or cache semantic matches.

**Image Conversion at Upload Time:**
- Issue: Base64 encoding happens during file upload (line 145 in `backend/app/routers/tasks.py`)
- Files: `backend/app/routers/tasks.py` (line 145)
- Impact: Large uploads are CPU-bound, block response
- Fix approach: Store files as-is, encode on-demand when building Claude messages. Use lazy loading.

**Full File Loading in Claude Context:**
- Issue: All file contents + metadata + chat history loaded into Claude message in `_build_messages_with_files` (lines 265-298 in `task_processor.py`)
- Files: `backend/app/services/task_processor.py`
- Impact: 20MB file → 26.7MB base64 string. Token limit hit for large documents. Slow serialization.
- Fix approach: For large files, extract relevant sections (OCR key areas for images, extract text for PDFs). Use Claude's document API when available.

**No Connection Pooling Visibility:**
- Issue: Database pool size is hardcoded (pool_size=10, max_overflow=20 in `backend/app/database.py` line 21)
- Files: `backend/app/database.py`
- Impact: Can't tune for production load. No monitoring of pool exhaustion.
- Fix approach: Make pooling configurable. Add monitoring: log pool utilization, queue wait time. Alert on exhaustion.

**Progress Update Causes Commit Per Message:**
- Issue: `update_progress` (lines 219-228 in `task_processor.py`) commits transaction for every progress message
- Files: `backend/app/services/task_processor.py`
- Impact: During processing, multiple database commits per request. Row locks held longer than needed.
- Fix approach: Batch progress updates. Update once at major milestones or buffer for ~5 seconds.

---

## Known Bugs

**JSON Response Parsing Fails on Nested Objects:**
- Symptoms: Claude returns valid JSON with nested structure, task fails with "Не удалось распознать ответ Claude как JSON"
- Files: `backend/app/services/task_processor.py` (lines 300-318), specifically regex at line 310
- Trigger: When Claude response has JSON with nested braces, e.g., `{..., "notes": "{...}"}` or multiple top-level objects
- Workaround: Claude instructions specify "СТРОГО в формате JSON (без markdown блоков)" but sometimes still wraps in markdown
- Root cause: Simple regex `\{[\s\S]*\}` is greedy and stops at first closing brace

**File Download Loses Encoding:**
- Symptoms: Downloaded Excel file has Cyrillic filename corrupted
- Files: `backend/app/routers/results.py` (lines 78-80)
- Trigger: Non-ASCII filename with special characters
- Current workaround: RFC 5987 encoding used but may not work in all browsers
- Fix: Add fallback ASCII filename, use Content-Disposition with explicit charset

**Chat Message Reprocessing Loses Context:**
- Symptoms: After sending follow-up message to task, previous chat history sometimes missing from result
- Files: `backend/app/routers/tasks.py` (lines 213-248), `backend/app/services/task_processor.py` (lines 293-296)
- Trigger: Large chat history > ~2000 tokens, or concurrent requests
- Root cause: `chat_history` is stored as JSON list in database, updated without validation. No schema enforcement.

**XLSX Parser Breaks on Merged Cells:**
- Symptoms: Excel files with merged cells produce garbled output
- Files: `backend/app/utils/file_parser.py` (lines 11-37)
- Trigger: Input Excel file has merged cells (common in construction docs)
- Root cause: openpyxl by default doesn't follow merged cell ranges, reads raw cells

---

## Fragile Areas

**API Response Format Contracts:**
- Files: `backend/app/routers/tasks.py`, `backend/app/services/task_processor.py`
- Why fragile: Frontend TypeScript assumes specific field names and types (e.g., `error_message`, `progress_message`). Backend code is not explicitly typed for response. Changes break silently.
- Safe modification: Define Pydantic response models for all endpoints, use them everywhere, add integration tests
- Test coverage: No tests verifying response format consistency

**Claude Prompt Injection via User Input:**
- Files: `backend/app/services/task_processor.py` (lines 288-289 where user_prompt is appended), `backend/app/routers/tasks.py` (line 165)
- Why fragile: User can inject prompt directives into `user_prompt` field, changing Claude's behavior
- Safe modification: Sanitize user_prompt: remove leading/trailing whitespace, reject if contains system prompt keywords, add explicit "User Requirements:" label
- Test coverage: No fuzzing tests for malicious prompts

**Auth Token Expiry Not Enforced:**
- Files: `backend/app/utils/auth.py` (lines 23-31 create token with exp), `frontend/src/api/client.ts` (no expiry check)
- Why fragile: Frontend doesn't check token expiry locally. Expired token accepted by backend until next API call triggers 401.
- Safe modification: Add token expiry check in frontend before API call. Refresh token endpoint for extending sessions.
- Test coverage: No tests for expired token handling

**Task Status State Machine Not Enforced:**
- Files: `backend/app/models/task.py` (line 19, status is just String), `backend/app/services/task_processor.py` (lines 230-240, status updates)
- Why fragile: Status is string enum in code only. Database allows any value. Can transition from completed → processing invalid ways.
- Safe modification: Use enum.Enum for status, add validation in update_status, log state transitions
- Test coverage: No tests for invalid state transitions

---

## Missing Critical Features

**No Audit Trail:**
- Problem: No logging of who created tasks, what actions were taken, API access patterns
- Files: System-wide - logging exists but doesn't capture user context
- Blocks: Compliance, debugging user issues, security investigation
- Fix: Add audit log table with user, action, resource, timestamp, result. Populate from all routers.

**No Task Cancellation:**
- Problem: Long-running tasks (SMETA_FROM_TZ_PROJECT with web search) can't be stopped by user
- Files: `backend/app/services/task_processor.py` (process method has no cancellation check)
- Blocks: User can't interrupt mistaken task. Wastes API quota.
- Fix: Check task status in processing loop every 10 seconds. Support status="cancelled" transition.

**No Result Filtering or Search:**
- Problem: Frontend lists all results, no pagination, no date filter
- Files: `frontend/src/pages/TaskStatus.tsx`, `backend/app/routers/results.py` (lines 26-54)
- Blocks: UX breaks with 100+ results
- Fix: Add pagination (limit, offset), date range filter, sort by created_at. Update frontend.

**No Concurrent Task Limits:**
- Problem: User can submit infinite tasks simultaneously
- Files: `backend/app/routers/tasks.py` (lines 95-183, no user-level concurrency check)
- Blocks: Single user can DOS system
- Fix: Track active tasks per user. Limit to 3 concurrent. Return 429 if exceeded.

**No Error Recovery for Failed Tasks:**
- Problem: Failed tasks can't be retried. User must recreate from scratch.
- Files: `backend/app/routers/tasks.py` (no retry endpoint), `backend/app/services/task_processor.py` (exception handling stops processing)
- Blocks: Transient errors (rate limit, network timeout) can't be recovered
- Fix: Add retry button on failed tasks. Implement exponential backoff in task processor.

---

## Test Coverage Gaps

**No Tests for Authentication Edge Cases:**
- What's not tested: Token expiry, invalid tokens, missing Authorization header, concurrent login attempts
- Files: `backend/app/utils/auth.py`, `backend/app/routers/auth.py`
- Risk: Authentication bypass bugs go undetected
- Priority: High

**No Tests for File Upload Validation:**
- What's not tested: MIME type mismatch (file claims .pdf but is actually .xlsx), files at size boundary (20MB - 1 byte vs 20MB + 1 byte), malformed files that crash parser
- Files: `backend/app/routers/tasks.py` (lines 106-156), `backend/app/utils/file_parser.py`
- Risk: Parser crashes or accepts invalid data
- Priority: High

**No Integration Tests for Task Processing:**
- What's not tested: Complete flow from task creation → Claude call → result generation. Real file parsing with actual construction documents.
- Files: `backend/app/services/task_processor.py`, `backend/app/services/excel_service.py`
- Risk: Task failure modes discovered in production
- Priority: Medium

**No Tests for Concurrent Task Execution:**
- What's not tested: Multiple users submitting tasks simultaneously, database transaction conflicts, race conditions in progress updates
- Files: `backend/app/routers/tasks.py`, `backend/app/services/task_processor.py`
- Risk: Data corruption under load
- Priority: Medium

**No Frontend Integration Tests:**
- What's not tested: Form validation, upload progress accuracy, error message display, login redirect on 401
- Files: `frontend/src/pages/TaskCreate.tsx`, `frontend/src/pages/Login.tsx`, `frontend/src/api/client.ts`
- Risk: UX broken in production
- Priority: Medium

**No Tests for Price Service Fallback Chain:**
- What's not tested: Exact match vs semantic match vs web search. Cache loading, cache miss handling.
- Files: `backend/app/services/price_service.py` (lines 225-256)
- Risk: Price fetching silently returns None, producing incomplete estimates
- Priority: Low

---

## Scaling Limits

**Database Row Size Limit:**
- Current capacity: Task model stores base64 file contents in JSON column - limited by PostgreSQL max row size (~1.6GB theoretical, ~1GB practical)
- Limit: With 10 files × 20MB each = 200MB, approaching limits
- Scaling path: Move file storage off-database (S3, local filesystem). Keep only file metadata in database.

**Claude API Rate Limits:**
- Current capacity: Configured with hardcoded retry delays (1, 4, 16 seconds) but no backoff on rate limit
- Limit: 100,000 tokens/minute soft limit. Price service makes additional semantic search calls (2+ calls per unmatched item)
- Scaling path: Implement token budget tracking. Queue requests. Use batch operations where possible.

**In-Memory Price Cache Growth:**
- Current capacity: Assumes price database fits in memory (`_works_cache`, `_materials_cache` as lists)
- Limit: Unknown. If price DB grows to 100k+ items, memory footprint becomes unacceptable
- Scaling path: Replace in-memory cache with Redis or implement pagination/filtering in price lookups.

**Database Connection Pool Saturation:**
- Current capacity: pool_size=10, max_overflow=20 = 30 concurrent connections
- Limit: With 10 concurrent users × 3 requests each = potential queue
- Scaling path: Add connection monitoring. Use async connection pooling with queue management. Scale horizontally with read replicas.

---

## Dependencies at Risk

**anthropic==0.40.0:**
- Risk: Version pinned to older release. Claude API evolving (web search tool recently added in v0.40+)
- Impact: Features unavailable, security patches missed
- Migration plan: Pin to ^0.45. Test new features. Automate dependency updates with renovate.

**weasyprint==63.1:**
- Risk: Known memory leaks in PDF generation from HTML. No active maintenance.
- Impact: Long-running server generates memory leak when generating comparison reports
- Migration plan: Evaluate reportlab or pypdf alternatives. Test memory usage under load.

**openpyxl==3.1.5:**
- Risk: Doesn't handle all Excel features (merged cells, macros, embedded objects)
- Impact: Construction estimates with complex formatting fail silently
- Migration plan: Evaluate python-docx + openpyxl combo or pandas for better coverage

**slowapi==0.1.9:**
- Risk: Project has low activity. Single rate limit middleware, no distributed rate limiting
- Impact: Rate limiting doesn't work across multiple server instances
- Migration plan: Use Redis-backed rate limiting (limits library) or API gateway solution

---

*Concerns audit: 2026-03-17*
