# Technology Stack

**Analysis Date:** 2026-03-17

## Languages

**Primary:**
- Python 3.12 - Backend API and services (`backend/`)
- TypeScript 5.6.3 - Frontend and build configuration (`frontend/`)
- JavaScript/JSX - React components and configuration

**Secondary:**
- SQL - PostgreSQL database schema
- YAML - Docker Compose and Render deployment configuration

## Runtime

**Environment:**
- Python 3.12-slim (Docker image: `python:3.12-slim`)
- Node.js 20 (Docker image: `node:20-alpine`) - Frontend build only
- Nginx (Alpine) - Frontend serving in production

**Package Manager:**
- pip (Python) - backend dependencies
- npm (Node.js) - frontend dependencies
- Lockfile: Not detected (npm uses package-lock.json implicitly)

## Frameworks

**Core:**
- FastAPI 0.115.5 - REST API framework, async request handling (`backend/app/main.py`)
- React 18.3.1 - Frontend UI framework (`frontend/src/`)
- React Router DOM 6.28.0 - Client-side routing

**Build/Dev:**
- Vite 5.4.11 - Frontend build tool and dev server (`frontend/vite.config.ts`)
- TypeScript 5.6.3 - Type safety for frontend
- Uvicorn 0.32.1 - ASGI server for FastAPI
- Alembic 1.14.0 - Database migrations (`backend/alembic/`)

**API/Async:**
- SQLAlchemy 2.0.36 with asyncio support - ORM for database operations
- asyncpg 0.30.0 - Async PostgreSQL driver

## Key Dependencies

**Backend - AI Integration:**
- anthropic 0.40.0 - Claude API client with streaming support (`backend/app/services/claude_service.py`)

**Backend - Authentication & Security:**
- python-jose[cryptography] 3.3.0 - JWT token handling
- bcrypt 4.2.1 - Password hashing (`backend/app/utils/auth.py`)
- pydantic-settings 2.6.1 - Configuration management (`backend/app/config.py`)

**Backend - File Processing:**
- openpyxl 3.1.5 - Excel file reading/writing (`backend/app/services/excel_service.py`)
- weasyprint 63.1 - PDF generation from HTML (`backend/app/services/pdf_service.py`)
- aiofiles 24.1.0 - Async file operations

**Backend - HTTP Client:**
- httpx 0.28.0 - Async HTTP client for external requests

**Backend - Utilities:**
- python-multipart 0.0.12 - Form data parsing for file uploads
- slowapi 0.1.9 - Rate limiting middleware (`backend/app/main.py`)
- structlog 24.4.0 - Structured logging (`backend/app/main.py`)

**Frontend - HTTP Client:**
- axios 1.7.9 - HTTP client with interceptors (`frontend/src/api/client.ts`)

**Frontend - State Management:**
- zustand 5.0.2 - Lightweight state management library

**Frontend - React Types:**
- @types/react 18.3.13
- @types/react-dom 18.3.1
- @vitejs/plugin-react 4.3.4

## Configuration

**Environment:**
- Managed via `.env` file (example: `.env.example`)
- Settings loaded with pydantic-settings (`backend/app/config.py`)
- Required vars: ANTHROPIC_API_KEY, DATABASE_URL, JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRE_HOURS, USER_PASSWORD, ADMIN_PASSWORD, MAX_FILE_SIZE_MB, MAX_FILES_PER_REQUEST, TASK_TIMEOUT_SECONDS, CORS_ORIGINS

**Build:**
- Frontend build config: `frontend/vite.config.ts` (Vite)
- Backend config: `backend/alembic.ini` (database migrations)
- Docker: `backend/Dockerfile` (Python backend), `frontend/Dockerfile` (Node + Nginx)

## Platform Requirements

**Development:**
- Python 3.9+ required (tested on 3.9.6, deployed on 3.12)
- Node.js 20+ for frontend builds
- PostgreSQL 16 (via Docker Compose)

**Production:**
- Deployment: Render.com (via `render.yaml`)
  - Backend: Python web service
  - Frontend: Static site deployment with SPA routing
- Docker Compose locally: PostgreSQL 16-alpine, FastAPI backend, Nginx frontend
- Database: PostgreSQL with asyncio + asyncpg driver

## Deployment Architecture

**Local Development:**
- Docker Compose orchestrates all services (`docker-compose.yml`)
- Backend service: uvicorn with --reload for hot reloading
- Frontend service: Nginx serving built dist/ from multi-stage Docker build
- Database: PostgreSQL volume persistence

**Production (Render):**
- Two separate services defined in `render.yaml`:
  - `smeta-ai-backend`: Python web service with manual env vars
  - `smeta-ai-frontend`: Static site with SPA routing (rewrite all routes to index.html)
- Database: External PostgreSQL (not managed by Render config)
- Frontend served as static files with 404 routing to index.html for SPA navigation

---

*Stack analysis: 2026-03-17*
