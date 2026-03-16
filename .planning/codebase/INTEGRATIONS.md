# External Integrations

**Analysis Date:** 2026-03-17

## APIs & External Services

**AI & Content Generation:**
- Claude (Anthropic) - Construction estimate generation and document analysis
  - SDK/Client: anthropic 0.40.0
  - Model: claude-sonnet-4-0
  - Features: Streaming responses, web search tool, image/document processing
  - Auth: `ANTHROPIC_API_KEY` environment variable
  - Integration: `backend/app/services/claude_service.py`
  - Usage:
    - List generation from technical specs
    - Estimate pricing and calculations
    - Document scanning and recognition
    - Project vs. estimate comparison
  - Web Search Tool: Enabled via `web_search_20250305` tool for price lookups

## Data Storage

**Databases:**
- PostgreSQL 16
  - Connection: `DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/smeta_ai`
  - Client: SQLAlchemy 2.0.36 with asyncio support
  - Driver: asyncpg 0.30.0 for async operations
  - Pool Configuration: pool_size=10, max_overflow=20 (in `backend/app/database.py`)
  - Migration Tool: Alembic 1.14.0 (migrations in `backend/alembic/`)
  - Tables: users, tasks, task_results, prices
  - Connection URL transformation: Automatically converts postgres:// to postgresql+asyncpg:// protocol

**File Storage:**
- Local filesystem only
  - Task result files stored in database as BYTEA: `backend/app/models/result.py`
  - File types: Excel (.xlsx), PDF (.pdf)
  - Uploaded files: Stored as base64-encoded strings in Task.input_file_data

**Caching:**
- Price cache in memory during task processing
  - Implementation: `backend/app/services/price_service.py`
  - Database-backed: Prices loaded from PostgreSQL price table into memory

## Authentication & Identity

**Auth Provider:**
- Custom JWT-based authentication
  - Implementation: Token-based with role separation
  - Location: `backend/app/routers/auth.py`
  - Algorithm: HS256
  - Expiration: Configurable via JWT_EXPIRE_HOURS (default: 24 hours)
  - Roles: "user" and "admin"
  - Password Hashing: bcrypt 4.2.1

**Auth Flow:**
1. Login with credentials (role + password)
2. Backend generates JWT token via python-jose
3. Frontend stores token in localStorage
4. Axios interceptor attaches Bearer token to all requests
5. Unauthorized requests (401) trigger logout and redirect to login page

**Default Users:**
- Created on first startup if they don't exist:
  - User role: password from USER_PASSWORD env var
  - Admin role: password from ADMIN_PASSWORD env var
  - Passwords hashed with bcrypt before storage

## Monitoring & Observability

**Error Tracking:**
- None detected (errors logged only)

**Logs:**
- structlog 0.24.4 for structured logging
  - Format: ISO timestamps, context variables, log levels
  - Output: Console renderer for local development
  - Location: `backend/app/main.py` (configured with structlog)
  - Usage: Error handling, API calls, task processing progress

**Rate Limiting:**
- slowapi 0.1.9 for API rate limiting
  - Middleware: SlowAPIMiddleware in FastAPI app
  - Strategy: Per IP address via get_remote_address
  - Handler: Custom exception handler for RateLimitExceeded

## Webhooks & Callbacks

**Incoming:**
- None detected

**Outgoing:**
- None detected

## CORS Configuration

**Allowed Origins:**
- Configured via CORS_ORIGINS environment variable
- Default (development): `http://localhost:5173,http://localhost:3000`
- Production (Render): `["*"]` - all origins allowed
- Implementation: `backend/app/main.py` (CORSMiddleware from fastapi)

## External File Formats Supported

**Input:**
- PDF documents (scanned estimates, technical specs, project docs)
- Excel files (.xlsx) - project data, material lists
- Images (for document scanning and OCR-like processing)
- DOCX (via skills directory, not directly in main app)

**Output:**
- Excel files (.xlsx) - list generation, estimate sheets
- PDF files - comparison reports

## Internal Async Architecture

**Background Task Processing:**
- FastAPI with asyncio
- No external job queue (Redis, Celery, etc.)
- Async task processor: `backend/app/services/task_processor.py`
- Tasks stored in database with status tracking
- Frontend polls task status via `/api/tasks/{id}` endpoint

**HTTP Client:**
- httpx 0.28.0 for async HTTP requests
- Timeout configuration: TASK_TIMEOUT_SECONDS (default: 600s)

## Security & Credentials

**Secrets Management:**
- Environment variables (`.env` file)
- Required secrets:
  - `ANTHROPIC_API_KEY` - Claude API key (sk-ant-...)
  - `JWT_SECRET` - JWT signing key (change in production)
  - `USER_PASSWORD` - Initial user account password
  - `ADMIN_PASSWORD` - Initial admin account password
  - `DATABASE_URL` - PostgreSQL connection string

**Upload Constraints:**
- MAX_FILE_SIZE_MB: 20 MB per file
- MAX_FILES_PER_REQUEST: 10 files per request
- Implemented in: `backend/app/routers/tasks.py`

---

*Integration audit: 2026-03-17*
