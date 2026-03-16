# Codebase Structure

**Analysis Date:** 2026-03-17

## Directory Layout

```
smeta-ai/
├── frontend/                      # React SPA - user-facing interface
│   ├── public/                    # Static assets (favicon, etc.)
│   ├── src/
│   │   ├── api/                   # HTTP client and API endpoint wrappers
│   │   ├── components/            # Reusable React components
│   │   ├── pages/                 # Page-level components (routed)
│   │   ├── stores/                # Zustand state stores
│   │   ├── types/                 # TypeScript interface definitions
│   │   ├── App.tsx                # Root router component
│   │   ├── main.tsx               # Entry point
│   │   └── index.css              # Global styles
│   ├── package.json               # Dependencies (React, React Router, Axios, Zustand)
│   ├── tsconfig.json              # TypeScript configuration
│   ├── vite.config.ts             # Vite build config with dev proxy
│   └── index.html                 # HTML template
│
├── backend/                       # FastAPI REST API server
│   ├── app/
│   │   ├── routers/               # API endpoint handlers
│   │   │   ├── auth.py            # POST /auth/login
│   │   │   ├── tasks.py           # POST /tasks, GET /tasks/{id}/status, POST /tasks/{id}/message
│   │   │   ├── results.py         # GET /results/{fileId}/download
│   │   │   └── admin.py           # Admin-only endpoints
│   │   ├── services/              # Business logic
│   │   │   ├── task_processor.py  # Task execution orchestrator
│   │   │   ├── claude_service.py  # Claude API wrapper
│   │   │   ├── excel_service.py   # Excel file generation
│   │   │   ├── pdf_service.py     # PDF report generation
│   │   │   └── price_service.py   # Construction pricing cache
│   │   ├── models/                # SQLAlchemy ORM models
│   │   │   ├── task.py            # Task data model
│   │   │   ├── result.py          # TaskResult data model
│   │   │   ├── user.py            # User data model
│   │   │   └── price.py           # Price data model
│   │   ├── utils/                 # Utility functions
│   │   │   ├── auth.py            # JWT, password hashing, token verification
│   │   │   └── file_parser.py     # Parse PDF, Excel, images, XML
│   │   ├── config.py              # Settings from environment variables
│   │   ├── database.py            # SQLAlchemy async setup, session factory
│   │   └── main.py                # FastAPI app creation and startup
│   ├── tests/                     # Test suite (if present)
│   ├── alembic/                   # Database migrations
│   │   └── versions/              # Migration files
│   └── requirements.txt           # Python dependencies
│
├── skills/                        # Plugin/extension modules (not part of core app)
│   ├── theme-factory/
│   ├── doc-coauthoring/
│   ├── claude-api/
│   ├── xlsx/
│   ├── pdf/
│   └── [11 more skill modules]    # Various specialized skills
│
├── .planning/
│   └── codebase/                  # Documentation artifacts (this directory)
│       ├── ARCHITECTURE.md        # Architecture patterns and layers
│       ├── STRUCTURE.md           # This file - directory layout
│       ├── CONVENTIONS.md         # Coding standards
│       └── TESTING.md             # Test patterns
│
├── render.yaml                    # Render.com deployment config
├── docker-compose.yml             # Local dev environment setup
├── .env.example                   # Template for environment variables
└── .gitignore                     # Git exclusions

```

## Directory Purposes

**frontend/src/api:**
- Purpose: HTTP communication layer between frontend and backend
- Contains: Axios client configuration, typed API wrapper functions
- Key files:
  - `client.ts`: Creates axios instance with base URL and request interceptors
  - `tasks.ts`: Functions for task CRUD (createTask, getTaskStatus, getTaskResults, sendMessage, downloadResult)
  - `auth.ts`: Login and token management
  - `admin.ts`: Admin-specific endpoints

**frontend/src/components:**
- Purpose: Reusable UI components
- Contains: Form inputs, layout wrappers, authentication guards
- Key files:
  - `Layout.tsx`: Header, navigation, container
  - `ProtectedRoute.tsx`: Route guard - redirects unauthenticated users to /login
  - `TaskTypeSelector.tsx`: Radio buttons for selecting task type
  - `FileUpload.tsx`: Drag-and-drop file input with validation

**frontend/src/pages:**
- Purpose: Full-page components corresponding to routes
- Contains: Form handling, data fetching, page-level logic
- Key files:
  - `Login.tsx`: Authentication form, sets token/role in store
  - `TaskCreate.tsx`: Task submission form with file upload progress
  - `TaskStatus.tsx`: Poll task status, display progress and results
  - `Admin.tsx`: Admin dashboard (role filtering)

**frontend/src/stores:**
- Purpose: Client-side state management
- Contains: Zustand store definitions
- Key files:
  - `auth.ts`: AuthState with token, role, setAuth(), logout() methods

**frontend/src/types:**
- Purpose: Shared TypeScript interfaces
- Contains: Task, TaskResult, User type definitions
- Key files:
  - `index.ts`: All exported types

**backend/app/routers:**
- Purpose: HTTP endpoint handlers
- Contains: Request parsing, response formatting, dependency injection
- Pattern: Each file exports a `router` (FastAPI APIRouter) with endpoints
- Key files:
  - `auth.py`: POST /auth/login - validates password, returns JWT token
  - `tasks.py`: POST /tasks - creates task; GET /tasks/{id}/status - returns status; POST /tasks/{id}/message - chat
  - `results.py`: GET /results/{fileId}/download - serves file binary
  - `admin.py`: Admin-only endpoints (list users, reset passwords, etc.)

**backend/app/services:**
- Purpose: Business logic and external integrations
- Contains: Task orchestration, Claude API calls, file generation
- Key files:
  - `task_processor.py`: TaskProcessor class - routes tasks, manages state, calls Claude
  - `claude_service.py`: call_claude() - wrapper around Anthropic API with tools
  - `excel_service.py`: generate_list(), generate_smeta(), generate_scan_result() - openpyxl
  - `pdf_service.py`: generate_comparison_report() - reportlab
  - `price_service.py`: Database cache for Russian construction prices (FER/TER/GESN)

**backend/app/models:**
- Purpose: SQLAlchemy ORM models mapping to database tables
- Contains: Column definitions, relationships, validation
- Key files:
  - `task.py`: Task model - UUID id, status, input_files (JSON), chat_history (JSON), progress_message, error_message
  - `result.py`: TaskResult model - task_id (FK), file_name, mime_type, file_data (binary)
  - `user.py`: User model - id, role (user/admin), password_hash
  - `price.py`: Price model - caches construction costs

**backend/app/utils:**
- Purpose: Cross-cutting utility functions
- Contains: Authentication, file parsing
- Key files:
  - `auth.py`: hash_password(), verify_password(), create_access_token(), verify_token(), get_current_user() dependency
  - `file_parser.py`: parse_file() - detects MIME type, returns text or image blocks for Claude

**backend/app:**
- Purpose: Core application initialization and configuration
- Key files:
  - `main.py`: create_app() factory, FastAPI initialization, startup/shutdown handlers
  - `config.py`: Settings class reading from environment (DATABASE_URL, ANTHROPIC_API_KEY, etc.)
  - `database.py`: SQLAlchemy engine, AsyncSessionLocal, Base class, init_db(), get_db()

## Key File Locations

**Entry Points:**
- `frontend/src/main.tsx`: React DOM mount point
- `frontend/index.html`: HTML container (`<div id="root">`)
- `backend/app/main.py`: FastAPI app creation (app = create_app())

**Configuration:**
- `frontend/.env.local` (not committed): Frontend API URL override
- `backend/.env` (not committed): DATABASE_URL, ANTHROPIC_API_KEY, JWT_SECRET, etc.
- `frontend/vite.config.ts`: Dev proxy to backend at http://localhost:8000

**Core Logic:**
- `backend/app/services/task_processor.py`: Task execution orchestrator
- `backend/app/services/claude_service.py`: Claude API calls
- `frontend/src/pages/TaskCreate.tsx`: Task submission
- `frontend/src/pages/TaskStatus.tsx`: Progress monitoring

**Testing:**
- `backend/tests/`: Pytest test suite (if present)
- No frontend tests currently (could add Vitest)

## Naming Conventions

**Files:**
- Python: snake_case (task_processor.py, file_parser.py)
- TypeScript: camelCase for components (TaskCreate.tsx), camelCase for utilities (client.ts, auth.ts)
- React components: PascalCase (TaskCreate.tsx, FileUpload.tsx)

**Directories:**
- All lowercase (src, api, components, pages, stores, types, routers, services, models, utils)

**React Components:**
- Pattern: `ComponentName.tsx` (PascalCase)
- Example: `TaskCreate.tsx`, `ProtectedRoute.tsx`

**API Routes:**
- Pattern: `POST /endpoint`, `GET /endpoint/:id`
- Example: POST /tasks, GET /tasks/{taskId}/status

**Database Models:**
- Table names: plural lowercase (tasks, users, task_results, prices)
- Column names: snake_case (user_role, task_type, progress_message)

**Functions/Variables:**
- JavaScript: camelCase (createTask, handleSubmit, uploadPercent)
- Python: snake_case (create_task, _run_task_in_background, SYSTEM_BASE)

## Where to Add New Code

**New Feature (e.g., Export to PDF):**
- **Service logic:** `backend/app/services/` - create `pdf_export_service.py`
- **API endpoint:** `backend/app/routers/tasks.py` - add new POST handler
- **Frontend page:** `frontend/src/pages/ExportPDF.tsx`
- **Tests:** `backend/tests/test_pdf_export.py`

**New Component/Module:**
- **React Component:** `frontend/src/components/ComponentName.tsx`
- **Page Component:** `frontend/src/pages/PageName.tsx`
- **Backend Service:** `backend/app/services/feature_service.py`
- **Router:** `backend/app/routers/feature.py` and import in `backend/app/main.py`

**Utilities:**
- **Shared helpers:** `backend/app/utils/helper_name.py` or `frontend/src/utils/helper.ts`
- **Types:** Add to `frontend/src/types/index.ts`
- **Constants:** Define in service file or create `backend/app/constants.py`

**Authentication/Authorization:**
- Check `backend/app/utils/auth.py` for token/role helpers
- Use `get_current_user` dependency in routers
- Use `ProtectedRoute` component in frontend with optional `requireAdmin` prop

**Database Models:**
- Create new model in `backend/app/models/model_name.py`
- Import in `backend/app/database.py` init_db()
- Create alembic migration: `alembic revision --autogenerate -m "Add model_name table"`

**Async Background Tasks:**
- Pattern: Register in router with `background_tasks.add_task(_run_task_in_background, task_id)`
- Acquire fresh DB session inside background function
- Log errors, update database state on failure

## Special Directories

**backend/alembic/:**
- Purpose: Database schema versioning and migrations
- Generated: Yes (auto-generated from model changes with alembic)
- Committed: Yes (version files committed)
- Usage: `alembic upgrade head` to apply pending migrations

**.planning/codebase/:**
- Purpose: Architecture and code analysis documentation
- Generated: Yes (created by GSD mapping tool)
- Committed: Yes (reference docs for future development)

**frontend/public/:**
- Purpose: Static assets served without build processing
- Generated: No (manually added)
- Committed: Yes

**backend/tests/:**
- Purpose: Automated test suite
- Generated: No (manually written)
- Committed: Yes (encouraged)

**skills/:**
- Purpose: Plugin/extension modules (external integrations)
- Generated: No
- Committed: Yes (historical, not active in core app)

---

*Structure analysis: 2026-03-17*
