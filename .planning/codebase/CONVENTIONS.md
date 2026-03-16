# Coding Conventions

**Analysis Date:** 2026-03-17

## Naming Patterns

**Files:**
- TypeScript/React files: PascalCase for components (`FileUpload.tsx`, `Layout.tsx`), camelCase for services/utilities (`client.ts`, `auth.ts`)
- Python files: snake_case for modules and files (`task_processor.py`, `price_service.py`, `auth.py`)
- API route files: `{router_name}.py` in `backend/app/routers/`

**Functions:**
- TypeScript: camelCase (`validateAndAdd`, `handleSubmit`, `formatFileSize`)
- Python: snake_case (`normalize_text`, `verify_password`, `hash_password`)
- React component handlers: `handle{Action}` pattern (e.g., `handleSubmit`, `handleDrop`, `handleDragOver`)

**Variables:**
- TypeScript: camelCase for all variables and state (`isDragging`, `validationErrors`, `uploadPercent`)
- Python: snake_case (`max_size_bytes`, `input_file_data`, `accepted_extensions`)
- Constants: UPPER_SNAKE_CASE in both languages
  - `MAX_FILES = 10` (TypeScript)
  - `ALLOWED_MIME_TYPES = {...}` (Python)

**Types:**
- TypeScript: PascalCase interfaces (`FileUploadProps`, `TaskStatusResponse`, `AuthState`)
- Python: PascalCase for model classes (`Task`, `User`, `TaskResult`)
- TypeScript union types: PascalCase with pipe separator (`TaskType = 'LIST_FROM_TZ' | 'SMETA_FROM_LIST'`)

## Code Style

**Formatting:**
- No explicit formatter configured (no .prettierrc or .eslintrc files found)
- Observed consistent indentation: 2 spaces in TypeScript/React, 4 spaces in Python
- Line length appears to follow ~120 characters soft limit
- Inline styles in React use consistent camelCase property names

**Linting:**
- No explicit linter configuration found
- TypeScript strict mode enabled in `tsconfig.json` with:
  - `strict: true` - enforces all strict type-checking options
  - `noUnusedLocals: true` - flags unused variables
  - `noUnusedParameters: true` - flags unused parameters
  - `noFallthroughCasesInSwitch: true` - prevents fallthrough in switch statements

## Import Organization

**Order:**
1. Third-party libraries (React, routing, axios, utilities)
2. Local relative imports (components, services, utilities)
3. Type imports (interfaces, types)

**Examples:**
```typescript
// Frontend pattern (FileUpload.tsx)
import React, { useRef, useState, useCallback } from 'react';
import apiClient from './client';
import { Task, TaskResult } from '../types';
```

```python
# Backend pattern (routers/tasks.py)
import base64
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, ...
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import structlog

from app.database import get_db, AsyncSessionLocal
from app.models.task import Task
from app.utils.auth import get_current_user
```

**Path Aliases:**
- No aliases configured in frontend (uses relative imports)
- Backend uses `app` prefix for local imports (`from app.models`, `from app.services`)

## Error Handling

**Patterns:**

**TypeScript/React:**
- Try-catch with type assertion for error objects
```typescript
try {
  const task = await createTask(formData, onUploadProgress);
  navigate(`/task/${task.task_id}/status`);
} catch (err: unknown) {
  const axiosError = err as { response?: { data?: { detail?: string } } };
  setError(axiosError.response?.data?.detail ?? 'Ошибка при создании задачи. Попробуйте ещё раз.');
}
```
- State-based error display (setError for user-facing messages)
- Optional chaining and nullish coalescing for safe property access

**Python/FastAPI:**
- HTTPException with status code and detail message for API errors
```python
raise HTTPException(
    status_code=status.HTTP_400_BAD_REQUEST,
    detail="Превышено максимальное количество файлов",
)
```
- Global exception handler in main.py with logging to structlog
- Logging errors with context using structlog (logger.error with key=value pairs)
- Try-except for business logic with logging on failure

## Logging

**Framework:** structlog (Python backend only)

**Patterns:**

**Python Backend:**
- Initialize logger: `logger = structlog.get_logger()`
- Log with context: `logger.info("Task created", task_id=task_id, task_type=task_type)`
- Log levels: `.info()`, `.warning()`, `.error()` with key=value structured data
- Async context handling: logs capture context variables automatically
- Example locations:
  - `backend/app/main.py` - startup/shutdown lifecycle logging
  - `backend/app/routers/tasks.py` - request/response logging
  - `backend/app/services/task_processor.py` - processing step logging

**TypeScript Frontend:**
- No structured logging framework configured
- User-facing errors stored in component state (e.g., `error` state)
- Error messages displayed conditionally in UI with consistent styling

## Comments

**When to Comment:**
- Complex algorithm logic (e.g., semantic matching, file parsing)
- Non-obvious business rules (e.g., file type validation fallback logic)
- docstrings for public functions in Python

**JSDoc/TSDoc:**
- Used minimally in codebase
- Python docstrings present for key functions
- Example: `backend/app/utils/auth.py` has docstrings for authentication functions

**Comment Style:**
- Python: Triple-quoted docstrings, single-line comments with `#`
- TypeScript: `//` for inline comments, no extensive JSDoc observed

## Function Design

**Size:**
- Small, focused functions (20-60 lines typical)
- Complex workflows broken into separate service functions
- Examples: `normalize_text()` (5 lines), `validateAndAdd()` (20 lines)

**Parameters:**
- TypeScript components use interface props pattern
- Python functions use type hints with Optional/typing module
- Async functions explicit in both languages

**Return Values:**
- TypeScript: Type-annotated returns (implicit in components, explicit in services)
- Python: Type hints with `-> Type` syntax
- Errors returned via exceptions, not error codes

## Module Design

**Exports:**
- React components: `export default` with named export for testing
- Services: Named exports for specific functions
- Example: `export async function createTask(...)`

**Barrel Files:**
- Frontend: `types/index.ts` aggregates type definitions with constants
- Backend: Router barrel in `routers/__init__.py` (empty)
- Minimal barrel usage; imports are specific

**Example Organization:**
```typescript
// frontend/src/types/index.ts - Central type definitions
export type TaskType = 'LIST_FROM_TZ' | 'SMETA_FROM_LIST' | ...;
export interface Task { id: string; task_type: TaskType; status: TaskStatus; ... }
export const TASK_TYPE_LABELS: Record<TaskType, string> = { ... };
```

## Database and Data Patterns

**SQLAlchemy (Python):**
- Modern SQLAlchemy 2.0+ with async support
- Type hints using `Mapped[Type]` with `mapped_column()`
- Model example: `backend/app/models/task.py` uses UUID primary key with server-side generation
- Async context managers for database sessions: `async with AsyncSessionLocal() as db:`

**Type Safety:**
- TypeScript strict mode enforces proper typing
- Python uses `typing.Optional[Type]` for nullable values
- Both use union types for status/role enumerations

---

*Convention analysis: 2026-03-17*
