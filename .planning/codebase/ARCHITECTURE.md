# Architecture

**Analysis Date:** 2026-03-17

## Pattern Overview

**Overall:** Layered/Client-Server Architecture with Request-Response pattern for task processing

**Key Characteristics:**
- Clear separation between frontend (React SPA) and backend (FastAPI)
- Asynchronous task processing with background workers
- Role-based access control (user/admin)
- Streaming API responses with progress tracking
- AI-powered document analysis (Claude API integration)

## Layers

**Presentation Layer (Frontend):**
- Purpose: User interface for task creation, monitoring, and results viewing
- Location: `frontend/src/pages`, `frontend/src/components`
- Contains: React page components, form handlers, layout wrappers
- Depends on: API client layer, authentication store
- Used by: End users (user/admin roles)

**API/Routing Layer (Backend):**
- Purpose: HTTP endpoint handlers that receive requests and route to services
- Location: `backend/app/routers/` (auth.py, tasks.py, results.py, admin.py)
- Contains: FastAPI routers, request validation (Pydantic models), response models
- Depends on: Database layer, service layer, authentication utilities
- Used by: Frontend via HTTP requests

**Service Layer (Backend):**
- Purpose: Business logic for task processing, file handling, Claude API calls
- Location: `backend/app/services/`
- Contains:
  - `task_processor.py`: Orchestrates task execution, routes by task type (LIST_FROM_TZ, SMETA_FROM_TZ, etc.)
  - `claude_service.py`: Manages Claude API calls with web search tools
  - `excel_service.py`: Generates Excel output files
  - `pdf_service.py`: Generates PDF reports
  - `price_service.py`: Caches and retrieves construction pricing data
- Depends on: Models, database, external APIs
- Used by: Routers (API endpoints)

**Data/Persistence Layer (Backend):**
- Purpose: Database operations and ORM mapping
- Location: `backend/app/database.py`, `backend/app/models/`
- Contains:
  - `database.py`: SQLAlchemy async engine, session management, connection pooling
  - `models/`: SQLAlchemy ORM models (Task, User, TaskResult, Price)
- Depends on: PostgreSQL database (via asyncpg driver)
- Used by: Service layer, routers

**Utility Layer (Backend):**
- Purpose: Cross-cutting concerns and helpers
- Location: `backend/app/utils/`
- Contains:
  - `auth.py`: JWT token creation/verification, password hashing, bearer token extraction
  - `file_parser.py`: Parses PDF, Excel, images, XML files into text/structured data
- Used by: Routers, services

**State Management (Frontend):**
- Purpose: Client-side state persistence
- Location: `frontend/src/stores/auth.ts`
- Contains: Zustand store for authentication state (token, role, isAuthenticated)
- Pattern: Persists to localStorage

## Data Flow

**Task Creation Flow:**

1. User submits form (`TaskCreate.tsx`) with files, task type, optional prompt
2. Frontend posts multipart FormData to `POST /tasks`
3. Router handler (`tasks.py`) validates files, stores file content as base64 in JSON
4. Task record created in database with status="pending"
5. Router enqueues background task via FastAPI BackgroundTasks
6. Response returns task_id immediately to frontend
7. Background worker (`process_task`) acquires own DB session
8. Worker calls `TaskProcessor.process()` which routes by task_type
9. Each handler calls Claude API via `call_claude()` with system prompts
10. Claude response parsed as JSON, enriched with pricing data from DB cache
11. Output file generated (Excel/PDF) and saved to database as TaskResult
12. Task status updated: pending → processing → completed/failed

**Task Status Polling Flow:**

1. Frontend polls `GET /tasks/{taskId}/status` every 1-2 seconds
2. Returns current status, progress_message, error_message, timestamps
3. User sees real-time progress updates (e.g., "Анализ документов...")
4. When completed, frontend calls `GET /tasks/{taskId}/results`
5. Returns list of TaskResult records with file metadata
6. User clicks download, triggers `GET /results/{fileId}/download` with blob response

**State Management:**

- **Authentication State:** Stored in Zustand store + localStorage. Persists across page reloads.
- **Task State:** Stored in PostgreSQL database. Frontend polls for updates.
- **File Content:** Stored as base64 JSON in Task model for processing context, as binary in TaskResult for delivery.

## Key Abstractions

**TaskProcessor (Service):**
- Purpose: Encapsulates task execution logic and state updates
- Examples: `backend/app/services/task_processor.py`
- Pattern: Dispatcher pattern - routes task_type to handler methods
  - `_handle_list_from_tz()`: Extracts work/material items from documents
  - `_handle_smeta()`: Creates cost estimate with pricing
  - `_handle_scan_to_excel()`: OCR/recognition of construction estimates
  - `_handle_compare()`: Compares project docs against estimates

**Task (Data Model):**
- Purpose: Persistent representation of a background task
- Examples: `backend/app/models/task.py`
- Fields: id (UUID), user_role, task_type, status, input_files (JSON), progress_message, chat_history (JSON), created_at, updated_at
- Pattern: Append-only with optimistic updates (status/progress_message)

**API Client (Frontend):**
- Purpose: HTTP request wrapper with common headers, token injection
- Examples: `frontend/src/api/client.ts`, `frontend/src/api/tasks.ts`
- Pattern: Module exports typed async functions wrapping axios

**File Parsing Pipeline:**
- Purpose: Normalize diverse input formats (PDF, Excel, images, XML) to text
- Examples: `backend/app/utils/file_parser.py` → `parse_file()`
- Pattern: Dispatcher based on MIME type, returns either text string or dict with image blocks

## Entry Points

**Frontend Entry:**
- Location: `frontend/src/main.tsx`
- Triggers: Browser load of `index.html`
- Responsibilities:
  1. Mount React app to `#root` element
  2. Render App component (routing setup)
  3. Initialize localStorage-backed auth store

**Frontend Router (App):**
- Location: `frontend/src/App.tsx`
- Triggers: BrowserRouter initialization
- Responsibilities:
  1. Define all routes (/login, /task/create, /task/:taskId/status, /admin)
  2. Conditionally render or redirect based on authentication + role
  3. Wrap protected routes with ProtectedRoute component

**Backend Entry:**
- Location: `backend/app/main.py`
- Triggers: Application startup (uvicorn)
- Responsibilities:
  1. Create FastAPI app instance
  2. Initialize database tables on startup
  3. Create default user/admin accounts if missing
  4. Register CORS middleware, rate limiting, error handlers
  5. Mount routers (auth, tasks, results, admin)
  6. Expose /health endpoint

**Background Task Worker:**
- Location: `backend/app/routers/tasks.py` → `_run_task_in_background()`
- Triggers: BackgroundTasks.add_task() from create_task endpoint
- Responsibilities:
  1. Acquire fresh DB session
  2. Call TaskProcessor.process()
  3. Log errors and allow original request to return immediately

## Error Handling

**Strategy:** Synchronous validation + try-catch with graceful degradation

**Patterns:**

**Frontend:**
- Try-catch wraps API calls in handlers
- Errors shown in UI toast/inline messages
- Axios interceptors could add retry logic (not currently implemented)
- Example: `TaskCreate.tsx` catches errors on form submit

**Backend:**
- Try-catch in background task processor captures Claude API failures
- Updates Task.error_message + status="failed"
- Global exception handler returns 500 with generic message
- Logger captures full error stack for debugging
- Rate limiter returns 429 if exceeded

**File Validation:**
- Whitelist of allowed MIME types checked at upload
- Fallback to file extension if content-type missing/wrong
- Rejects .gsn files with friendly message

**Claude API Fallback:**
- If JSON parsing fails from Claude response, raises ValueError
- Task status updated to failed, error logged
- No retry logic (could be added to TaskProcessor.process())

## Cross-Cutting Concerns

**Logging:**
- Framework: structlog (Python), console.log (JavaScript)
- Backend: Structured logging with context (task_id, error, user)
- Frontend: Console logging for development, could add error reporting

**Validation:**
- Frontend: HTML5 form validation (required attributes)
- Backend: Pydantic models auto-validate request bodies
- File size/type validated at upload endpoint
- Claude response JSON validated by _parse_json_response()

**Authentication:**
- Pattern: JWT token in Authorization header ("Bearer {token}")
- Token created at `/auth/login` with role embedded
- Extracted via HTTPBearer dependency in get_current_user()
- Used in ProtectedRoute to block unauthorized access
- Roles: "user" (standard), "admin" (elevated, access to /admin)

**Database Transactions:**
- Pattern: Async context manager in get_db()
- Commits on success, rolls back on exception
- Pool size 10, max overflow 20 for concurrent requests
- Pre-ping enabled to detect stale connections

**Rate Limiting:**
- Framework: slowapi
- Applied globally via SlowAPIMiddleware
- Key function: get_remote_address (client IP)
- Config in settings (can be customized per endpoint with @limiter.limit decorator)

---

*Architecture analysis: 2026-03-17*
