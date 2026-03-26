# Projects Iteration 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Project entity + file slots (source/estimate/optimized) to the system, with a Projects tab in the UI showing cards with estimation aggregation.

**Architecture:** New `projects` table (UUID PK) with one-to-many to `tasks`. `task_results` gets a `slot` column. `tasks` gets `project_id`, `estimation_status`, and `cost`. Backend: new `/projects` router + file-slot endpoints on `/tasks`. Frontend: new Projects/ProjectDetail pages + file slot UI in TaskStatus + project selector in TaskCreate.

**Tech Stack:** FastAPI + SQLAlchemy 2.x async (asyncpg) + PostgreSQL / React + TypeScript + Vite + Zustand + axios / openpyxl (already installed) / pytest-asyncio + httpx (test suite)

---

### Task 1: xlsx cost parser utility + constants

**Files:**
- Create: `backend/app/constants.py`
- Create: `backend/app/utils/xlsx_cost_parser.py`
- Create: `backend/tests/test_xlsx_cost_parser.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_xlsx_cost_parser.py
import io
import pytest
from decimal import Decimal
import openpyxl

from app.utils.xlsx_cost_parser import extract_total_cost
from app.constants import ESTIMATE_TASK_TYPES


def _make_xlsx(rows: list[list]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_extract_total_cost_finds_итого():
    data = _make_xlsx([
        ["Работа", "Ед", "Кол", "Цена"],
        ["Копать ямы", "м3", 10, 5000],
        ["Итого", "", "", 50000],
    ])
    assert extract_total_cost(data) == Decimal("50000")


def test_extract_total_cost_finds_всего():
    data = _make_xlsx([
        ["Наименование", "Сумма"],
        ["Работы", 100000],
        ["Всего", 100000],
    ])
    assert extract_total_cost(data) == Decimal("100000")


def test_extract_total_cost_case_insensitive():
    data = _make_xlsx([
        ["  ИТОГО  ", "", 999.99],
    ])
    assert extract_total_cost(data) == Decimal("999.99")


def test_extract_total_cost_multiple_rows_returns_last():
    data = _make_xlsx([
        ["итого", "", 1000],
        ["Другие работы", "", 500],
        ["итого", "", 2000],
    ])
    assert extract_total_cost(data) == Decimal("2000")


def test_extract_total_cost_no_number_in_row_returns_none():
    data = _make_xlsx([
        ["итого", "нет числа", "—"],
    ])
    assert extract_total_cost(data) is None


def test_extract_total_cost_no_matching_row_returns_none():
    data = _make_xlsx([
        ["Работа", "Ед", "Цена"],
        ["Копать ямы", "м3", 5000],
    ])
    assert extract_total_cost(data) is None


def test_extract_total_cost_damaged_file_returns_none():
    assert extract_total_cost(b"not an xlsx file at all") is None


def test_extract_total_cost_float_value():
    data = _make_xlsx([
        ["ИТОГО", 123456.78],
    ])
    assert extract_total_cost(data) == Decimal("123456.78")


def test_estimate_task_types_constant():
    assert "SMETA_FROM_LIST" in ESTIMATE_TASK_TYPES
    assert "SMETA_FROM_PROJECT" in ESTIMATE_TASK_TYPES
    assert "SMETA_FROM_EDC_PROJECT" in ESTIMATE_TASK_TYPES
    assert "SMETA_FROM_GRAND_PROJECT" in ESTIMATE_TASK_TYPES
    assert "SCAN_TO_EXCEL" in ESTIMATE_TASK_TYPES
    assert "COMPARE_PROJECT_SMETA" not in ESTIMATE_TASK_TYPES
    assert "LIST_FROM_TZ" not in ESTIMATE_TASK_TYPES
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/admin/Desktop/смета\ аи/smeta-ai/backend
python -m pytest tests/test_xlsx_cost_parser.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.utils.xlsx_cost_parser'`

- [ ] **Step 3: Create constants.py**

```python
# backend/app/constants.py
ESTIMATE_TASK_TYPES = {
    "SMETA_FROM_LIST",
    "SMETA_FROM_PROJECT",
    "SMETA_FROM_EDC_PROJECT",
    "SMETA_FROM_GRAND_PROJECT",
    "SCAN_TO_EXCEL",
}
```

- [ ] **Step 4: Create xlsx_cost_parser.py**

```python
# backend/app/utils/xlsx_cost_parser.py
import io
from decimal import Decimal

import openpyxl


def extract_total_cost(file_bytes: bytes) -> Decimal | None:
    """
    Ищет строку где первая ячейка содержит 'итого' или 'всего'
    (регистронезависимо, после strip).
    Возвращает последнее числовое значение в этой строке.
    Если найдено несколько таких строк — берёт последнюю.
    Если ничего не найдено — возвращает None.
    """
    try:
        wb = openpyxl.load_workbook(
            io.BytesIO(file_bytes), read_only=True, data_only=True
        )
    except Exception:
        return None

    last_cost: Decimal | None = None

    for ws in wb.worksheets:
        for row in ws.iter_rows():
            if not row:
                continue
            first_val = row[0].value
            if first_val is None:
                continue
            normalized = str(first_val).strip().lower()
            if "итого" not in normalized and "всего" not in normalized:
                continue
            # Find last numeric value in this row
            for cell in reversed(row):
                val = cell.value
                if isinstance(val, (int, float)) and not isinstance(val, bool):
                    last_cost = Decimal(str(val))
                    break

    return last_cost
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd /Users/admin/Desktop/смета\ аи/smeta-ai/backend
python -m pytest tests/test_xlsx_cost_parser.py -v
```

Expected: all 9 tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/constants.py backend/app/utils/xlsx_cost_parser.py backend/tests/test_xlsx_cost_parser.py
git commit -m "feat: add ESTIMATE_TASK_TYPES constant and xlsx cost parser"
```

---

### Task 2: Project model

**Files:**
- Create: `backend/app/models/project.py`
- Modify: `backend/app/models/__init__.py`

- [ ] **Step 1: Create project.py**

```python
# backend/app/models/project.py
from typing import Optional
from sqlalchemy import String, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from datetime import datetime, timezone
from app.database import Base


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
```

- [ ] **Step 2: Update models/__init__.py**

```python
# backend/app/models/__init__.py
from app.models.user import User
from app.models.task import Task
from app.models.result import TaskResult
from app.models.price import PriceWork, PriceMaterial
from app.models.project import Project

__all__ = ["User", "Task", "TaskResult", "PriceWork", "PriceMaterial", "Project"]
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/models/project.py backend/app/models/__init__.py
git commit -m "feat: add Project model"
```

---

### Task 3: Migration 004 + .gitignore

**Files:**
- Create: `backend/alembic/versions/004_projects.py`
- Modify: `.gitignore`

- [ ] **Step 1: Create migration 004**

```python
# backend/alembic/versions/004_projects.py
"""Add projects table, task project/estimation fields, task_results slot

Revision ID: 004
Revises: 003
Create Date: 2026-03-26 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = [c["name"] for c in inspector.get_columns(table)]
    return column in cols


def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table in inspector.get_table_names()


def upgrade() -> None:
    # 1. Create projects table
    if not _table_exists("projects"):
        op.create_table(
            "projects",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=False),
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    # 2. Add project_id to tasks
    if not _column_exists("tasks", "project_id"):
        op.add_column(
            "tasks",
            sa.Column(
                "project_id",
                postgresql.UUID(as_uuid=False),
                sa.ForeignKey("projects.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        op.create_index("ix_tasks_project_id", "tasks", ["project_id"])

    # 3. Add estimation_status to tasks
    if not _column_exists("tasks", "estimation_status"):
        op.add_column(
            "tasks",
            sa.Column(
                "estimation_status",
                sa.String(20),
                nullable=False,
                server_default="not_applicable",
            ),
        )

    # 4. Add cost to tasks
    if not _column_exists("tasks", "cost"):
        op.add_column(
            "tasks",
            sa.Column("cost", sa.Numeric(12, 2), nullable=True),
        )

    # 5. Add slot to task_results
    if not _column_exists("task_results", "slot"):
        op.add_column(
            "task_results",
            sa.Column(
                "slot",
                sa.String(20),
                nullable=False,
                server_default="result",
            ),
        )


def downgrade() -> None:
    op.drop_column("task_results", "slot")
    op.drop_column("tasks", "cost")
    op.drop_column("tasks", "estimation_status")
    op.drop_index("ix_tasks_project_id", table_name="tasks")
    op.drop_column("tasks", "project_id")
    op.drop_table("projects")
```

- [ ] **Step 2: Add migration to .gitignore whitelist**

Edit `.gitignore` — add the line `!backend/alembic/versions/004_projects.py` after the existing `!003` line:

```
# Alembic
backend/alembic/versions/*.py
!backend/alembic/versions/001_initial.py
!backend/alembic/versions/002_price_lists.py
!backend/alembic/versions/003_fix_user_role_column_type.py
!backend/alembic/versions/004_projects.py
```

- [ ] **Step 3: Commit**

```bash
git add backend/alembic/versions/004_projects.py .gitignore
git commit -m "feat: migration 004 — projects table + estimation fields + slot column"
```

---

### Task 4: Update Task and TaskResult models + conftest

**Files:**
- Modify: `backend/app/models/task.py`
- Modify: `backend/app/models/result.py`
- Modify: `backend/tests/conftest.py`

- [ ] **Step 1: Update task.py**

Replace the contents of `backend/app/models/task.py`:

```python
from typing import Optional
from decimal import Decimal
from sqlalchemy import Integer, String, Text, DateTime, JSON, Numeric, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from datetime import datetime, timezone
from app.database import Base


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_role: Mapped[str] = mapped_column(String(10), nullable=False)
    task_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    input_files: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # Each entry: {name, mime_type, size_bytes, content_b64}
    input_file_data: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    user_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    chat_history: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    progress_message: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    project_id: Mapped[Optional[str]] = mapped_column(
        PG_UUID(as_uuid=False),
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    estimation_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="not_applicable",
    )
    cost: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
```

- [ ] **Step 2: Update result.py**

Replace the contents of `backend/app/models/result.py`:

```python
from sqlalchemy import Integer, String, DateTime, LargeBinary, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from datetime import datetime, timezone
from app.database import Base


class TaskResult(Base):
    __tablename__ = "task_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    slot: Mapped[str] = mapped_column(String(20), nullable=False, default="result")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    task = relationship("Task", foreign_keys=[task_id])
```

- [ ] **Step 3: Update conftest.py — add Project import**

In `backend/tests/conftest.py`, add one import line after the existing model imports:

```python
from app.models.project import Project  # noqa: F401  (registers with Base.metadata)
```

So the imports block becomes:

```python
from app.database import Base, get_db
from app.models.task import Task          # noqa: F401  (registers with Base.metadata)
from app.models.result import TaskResult  # noqa: F401
from app.models.user import User          # noqa: F401
from app.models.price import PriceWork, PriceMaterial  # noqa: F401
from app.models.price_list import PriceList             # noqa: F401
from app.models.project import Project    # noqa: F401
from app.utils.auth import hash_password, create_access_token
```

- [ ] **Step 4: Run existing tests to verify nothing broke**

```bash
cd /Users/admin/Desktop/смета\ аи/smeta-ai/backend
python -m pytest tests/ -v --ignore=tests/test_xlsx_cost_parser.py -x
```

Expected: all existing tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/task.py backend/app/models/result.py backend/tests/conftest.py
git commit -m "feat: add project_id/estimation_status/cost to Task; add slot to TaskResult"
```

---

### Task 5: Projects router (CRUD + aggregation)

**Files:**
- Create: `backend/app/routers/projects.py`
- Create: `backend/tests/test_projects_router.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_projects_router.py
import pytest
import pytest_asyncio
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_project(async_client: AsyncClient, user_token: str):
    resp = await async_client.post(
        "/projects",
        json={"name": "Тестовый проект", "description": "Описание"},
        headers={"Authorization": user_token},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Тестовый проект"
    assert data["description"] == "Описание"
    assert "id" in data


@pytest.mark.asyncio
async def test_list_projects(async_client: AsyncClient, user_token: str):
    await async_client.post(
        "/projects",
        json={"name": "Проект А"},
        headers={"Authorization": user_token},
    )
    resp = await async_client.get(
        "/projects",
        headers={"Authorization": user_token},
    )
    assert resp.status_code == 200
    items = resp.json()
    assert isinstance(items, list)
    assert len(items) >= 1
    item = items[0]
    assert "id" in item
    assert "name" in item
    assert "unestimated" in item
    assert "estimated" in item
    assert "optimized" in item
    assert "other" in item
    assert "total_cost" in item


@pytest.mark.asyncio
async def test_get_project_detail(async_client: AsyncClient, user_token: str):
    create_resp = await async_client.post(
        "/projects",
        json={"name": "Детальный проект"},
        headers={"Authorization": user_token},
    )
    project_id = create_resp.json()["id"]

    resp = await async_client.get(
        f"/projects/{project_id}",
        headers={"Authorization": user_token},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == project_id
    assert "tasks" in data


@pytest.mark.asyncio
async def test_patch_project(async_client: AsyncClient, user_token: str):
    create_resp = await async_client.post(
        "/projects",
        json={"name": "Старое название"},
        headers={"Authorization": user_token},
    )
    project_id = create_resp.json()["id"]

    resp = await async_client.patch(
        f"/projects/{project_id}",
        json={"name": "Новое название"},
        headers={"Authorization": user_token},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Новое название"


@pytest.mark.asyncio
async def test_delete_project_requires_admin(async_client: AsyncClient, user_token: str):
    create_resp = await async_client.post(
        "/projects",
        json={"name": "Удаляемый"},
        headers={"Authorization": user_token},
    )
    project_id = create_resp.json()["id"]

    resp = await async_client.delete(
        f"/projects/{project_id}",
        headers={"Authorization": user_token},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_delete_project_as_admin(async_client: AsyncClient, admin_token: str):
    create_resp = await async_client.post(
        "/projects",
        json={"name": "Удаляемый"},
        headers={"Authorization": admin_token},
    )
    project_id = create_resp.json()["id"]

    resp = await async_client.delete(
        f"/projects/{project_id}",
        headers={"Authorization": admin_token},
    )
    assert resp.status_code == 200

    # Project gone
    get_resp = await async_client.get(
        f"/projects/{project_id}",
        headers={"Authorization": admin_token},
    )
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_get_project_not_found(async_client: AsyncClient, user_token: str):
    resp = await async_client.get(
        "/projects/00000000-0000-0000-0000-000000000099",
        headers={"Authorization": user_token},
    )
    assert resp.status_code == 404
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /Users/admin/Desktop/смета\ аи/smeta-ai/backend
python -m pytest tests/test_projects_router.py -v
```

Expected: FAIL — 404 Not Found (router not registered)

- [ ] **Step 3: Create projects router**

```python
# backend/app/routers/projects.py
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, case, delete
from datetime import datetime, timezone
import structlog

from app.database import get_db
from app.models.project import Project
from app.models.task import Task
from app.utils.auth import get_current_user, get_admin_user

logger = structlog.get_logger()

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = None


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class ProjectResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    created_at: str
    updated_at: str


class ProjectCardResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    created_at: str
    updated_at: str
    unestimated: int
    estimated: int
    optimized: int
    other: int
    total_cost: Optional[float]


class TaskBrief(BaseModel):
    id: str
    task_type: str
    status: str
    estimation_status: str
    cost: Optional[float]
    created_at: str


class ProjectDetailResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    created_at: str
    updated_at: str
    unestimated: int
    estimated: int
    optimized: int
    other: int
    total_cost: Optional[float]
    tasks: list[TaskBrief]


def _project_to_response(p: Project) -> ProjectResponse:
    return ProjectResponse(
        id=str(p.id),
        name=p.name,
        description=p.description,
        created_at=p.created_at.isoformat(),
        updated_at=p.updated_at.isoformat(),
    )


async def _get_project_or_404(project_id: str, db: AsyncSession) -> Project:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Проект не найден")
    return project


async def _aggregate(project_id: str, db: AsyncSession) -> dict:
    stmt = select(
        func.count(case((Task.estimation_status == "unestimated", 1), else_=None)).label("unestimated"),
        func.count(case((Task.estimation_status == "estimated", 1), else_=None)).label("estimated"),
        func.count(case((Task.estimation_status == "optimized", 1), else_=None)).label("optimized"),
        func.count(case((Task.estimation_status == "not_applicable", 1), else_=None)).label("other"),
        func.sum(
            case(
                (Task.estimation_status.in_(["estimated", "optimized"]), Task.cost),
                else_=None,
            )
        ).label("total_cost"),
    ).where(Task.project_id == project_id)
    row = (await db.execute(stmt)).one()
    return {
        "unestimated": row.unestimated or 0,
        "estimated": row.estimated or 0,
        "optimized": row.optimized or 0,
        "other": row.other or 0,
        "total_cost": float(row.total_cost) if row.total_cost is not None else None,
    }


@router.post("", response_model=ProjectResponse)
async def create_project(
    body: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    project = Project(name=body.name, description=body.description)
    db.add(project)
    await db.commit()
    await db.refresh(project)
    logger.info("Project created", project_id=str(project.id), name=project.name)
    return _project_to_response(project)


@router.get("", response_model=list[ProjectCardResponse])
async def list_projects(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    result = await db.execute(
        select(Project).order_by(Project.created_at.desc())
    )
    projects = result.scalars().all()

    cards = []
    for p in projects:
        agg = await _aggregate(str(p.id), db)
        cards.append(ProjectCardResponse(
            id=str(p.id),
            name=p.name,
            description=p.description,
            created_at=p.created_at.isoformat(),
            updated_at=p.updated_at.isoformat(),
            **agg,
        ))
    return cards


@router.get("/{project_id}", response_model=ProjectDetailResponse)
async def get_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    project = await _get_project_or_404(project_id, db)
    agg = await _aggregate(project_id, db)

    tasks_result = await db.execute(
        select(Task).where(Task.project_id == project_id).order_by(Task.created_at.desc())
    )
    tasks = tasks_result.scalars().all()

    return ProjectDetailResponse(
        id=str(project.id),
        name=project.name,
        description=project.description,
        created_at=project.created_at.isoformat(),
        updated_at=project.updated_at.isoformat(),
        tasks=[
            TaskBrief(
                id=str(t.id),
                task_type=t.task_type,
                status=t.status,
                estimation_status=t.estimation_status,
                cost=float(t.cost) if t.cost is not None else None,
                created_at=t.created_at.isoformat(),
            )
            for t in tasks
        ],
        **agg,
    )


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    body: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    project = await _get_project_or_404(project_id, db)
    if body.name is not None:
        project.name = body.name
    if body.description is not None:
        project.description = body.description
    project.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(project)
    return _project_to_response(project)


@router.delete("/{project_id}")
async def delete_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    admin_user: dict = Depends(get_admin_user),
):
    project = await _get_project_or_404(project_id, db)
    # Nullify project_id on related tasks (ON DELETE SET NULL handles it in DB,
    # but we do it explicitly for SQLite compatibility in tests)
    await db.execute(
        Task.__table__.update()
        .where(Task.project_id == project_id)
        .values(project_id=None)
    )
    await db.delete(project)
    await db.commit()
    logger.info("Project deleted", project_id=project_id)
    return {"project_id": project_id, "status": "deleted"}
```

- [ ] **Step 4: Register router in main.py**

In `backend/app/main.py`, update the router imports section (lines 110–115):

```python
    # Include routers
    from app.routers import auth, tasks, results, admin, projects

    app.include_router(auth.router)
    app.include_router(tasks.router)
    app.include_router(results.router)
    app.include_router(admin.router)
    app.include_router(projects.router)
```

- [ ] **Step 5: Run tests**

```bash
cd /Users/admin/Desktop/смета\ аи/smeta-ai/backend
python -m pytest tests/test_projects_router.py -v
```

Expected: all 7 tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/projects.py backend/tests/test_projects_router.py backend/app/main.py
git commit -m "feat: projects CRUD router with aggregation"
```

---

### Task 6: File slot endpoints + estimation + project linking

**Files:**
- Modify: `backend/app/routers/tasks.py`
- Create: `backend/tests/test_task_file_slots.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_task_file_slots.py
import io
import pytest
import openpyxl
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.task import Task
from app.models.result import TaskResult


SEEDED_TASK_ID = "00000000-0000-0000-0000-000000000001"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _make_xlsx_with_итого(cost: float) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Работа", "Сумма"])
    ws.append(["Итого", cost])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _make_xlsx_no_итого() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Работа", "Сумма"])
    ws.append(["Нет итого", 500])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.mark.asyncio
async def test_upload_source_slot(
    async_client: AsyncClient,
    user_token: str,
    seed_users,
    db_session: AsyncSession,
):
    # Make sure seed task is an ESTIMATE type
    result = await db_session.execute(select(Task).where(Task.id == SEEDED_TASK_ID))
    task = result.scalar_one()
    task.task_type = "SMETA_FROM_LIST"
    task.estimation_status = "unestimated"
    await db_session.commit()

    xlsx_bytes = _make_xlsx_no_итого()
    resp = await async_client.post(
        f"/tasks/{SEEDED_TASK_ID}/files",
        headers={"Authorization": user_token},
        files={"file": ("source.xlsx", xlsx_bytes, XLSX_MIME)},
        data={"slot": "source"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["slot"] == "source"

    # Verify DB record
    res = await db_session.execute(
        select(TaskResult)
        .where(TaskResult.task_id == SEEDED_TASK_ID, TaskResult.slot == "source")
    )
    row = res.scalar_one_or_none()
    assert row is not None
    assert row.file_name == "source.xlsx"


@pytest.mark.asyncio
async def test_upload_estimate_slot_parses_cost(
    async_client: AsyncClient,
    user_token: str,
    seed_users,
    db_session: AsyncSession,
):
    result = await db_session.execute(select(Task).where(Task.id == SEEDED_TASK_ID))
    task = result.scalar_one()
    task.task_type = "SMETA_FROM_LIST"
    task.estimation_status = "unestimated"
    task.cost = None
    await db_session.commit()

    xlsx_bytes = _make_xlsx_with_итого(150000.50)
    resp = await async_client.post(
        f"/tasks/{SEEDED_TASK_ID}/files",
        headers={"Authorization": user_token},
        files={"file": ("estimate.xlsx", xlsx_bytes, XLSX_MIME)},
        data={"slot": "estimate"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["estimation_status"] == "estimated"
    assert data["cost"] == pytest.approx(150000.50, abs=0.01)


@pytest.mark.asyncio
async def test_upload_estimate_slot_damaged_xlsx_returns_warning(
    async_client: AsyncClient,
    user_token: str,
    seed_users,
    db_session: AsyncSession,
):
    result = await db_session.execute(select(Task).where(Task.id == SEEDED_TASK_ID))
    task = result.scalar_one()
    task.task_type = "SMETA_FROM_LIST"
    task.estimation_status = "unestimated"
    await db_session.commit()

    resp = await async_client.post(
        f"/tasks/{SEEDED_TASK_ID}/files",
        headers={"Authorization": user_token},
        files={"file": ("bad.xlsx", b"not really xlsx", XLSX_MIME)},
        data={"slot": "estimate"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["estimation_status"] == "unestimated"
    assert data["cost"] is None
    assert "warning" in data


@pytest.mark.asyncio
async def test_upload_non_xlsx_to_estimate_returns_400(
    async_client: AsyncClient,
    user_token: str,
    seed_users,
    db_session: AsyncSession,
):
    result = await db_session.execute(select(Task).where(Task.id == SEEDED_TASK_ID))
    task = result.scalar_one()
    task.task_type = "SMETA_FROM_LIST"
    task.estimation_status = "unestimated"
    await db_session.commit()

    resp = await async_client.post(
        f"/tasks/{SEEDED_TASK_ID}/files",
        headers={"Authorization": user_token},
        files={"file": ("doc.pdf", b"%PDF-fake", "application/pdf")},
        data={"slot": "estimate"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_delete_estimate_slot_clears_cost(
    async_client: AsyncClient,
    user_token: str,
    seed_users,
    db_session: AsyncSession,
):
    result = await db_session.execute(select(Task).where(Task.id == SEEDED_TASK_ID))
    task = result.scalar_one()
    task.task_type = "SMETA_FROM_LIST"
    task.estimation_status = "estimated"
    task.cost = 99000
    await db_session.commit()

    # Create a result row for the estimate slot
    slot_result = TaskResult(
        task_id=SEEDED_TASK_ID,
        file_name="estimate.xlsx",
        mime_type=XLSX_MIME,
        file_data=b"fake",
        slot="estimate",
    )
    db_session.add(slot_result)
    await db_session.commit()

    resp = await async_client.delete(
        f"/tasks/{SEEDED_TASK_ID}/files/estimate",
        headers={"Authorization": user_token},
    )
    assert resp.status_code == 200

    await db_session.refresh(task)
    assert task.cost is None
    assert task.estimation_status == "unestimated"


@pytest.mark.asyncio
async def test_confirm_optimized_estimation(
    async_client: AsyncClient,
    user_token: str,
    seed_users,
    db_session: AsyncSession,
):
    result = await db_session.execute(select(Task).where(Task.id == SEEDED_TASK_ID))
    task = result.scalar_one()
    task.task_type = "SMETA_FROM_LIST"
    task.estimation_status = "estimated"
    await db_session.commit()

    # Upload optimized file first
    slot_result = TaskResult(
        task_id=SEEDED_TASK_ID,
        file_name="optimized.xlsx",
        mime_type=XLSX_MIME,
        file_data=b"fake",
        slot="optimized",
    )
    db_session.add(slot_result)
    await db_session.commit()

    resp = await async_client.patch(
        f"/tasks/{SEEDED_TASK_ID}/estimation",
        json={"estimation_status": "optimized"},
        headers={"Authorization": user_token},
    )
    assert resp.status_code == 200
    assert resp.json()["estimation_status"] == "optimized"


@pytest.mark.asyncio
async def test_confirm_optimized_fails_without_file(
    async_client: AsyncClient,
    user_token: str,
    seed_users,
    db_session: AsyncSession,
):
    result = await db_session.execute(select(Task).where(Task.id == SEEDED_TASK_ID))
    task = result.scalar_one()
    task.task_type = "SMETA_FROM_LIST"
    task.estimation_status = "estimated"
    await db_session.commit()

    resp = await async_client.patch(
        f"/tasks/{SEEDED_TASK_ID}/estimation",
        json={"estimation_status": "optimized"},
        headers={"Authorization": user_token},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_patch_task_project(
    async_client: AsyncClient,
    user_token: str,
    seed_users,
    db_session: AsyncSession,
):
    # Create a project
    proj_resp = await async_client.post(
        "/projects",
        json={"name": "Тест проект"},
        headers={"Authorization": user_token},
    )
    project_id = proj_resp.json()["id"]

    resp = await async_client.patch(
        f"/tasks/{SEEDED_TASK_ID}/project",
        json={"project_id": project_id},
        headers={"Authorization": user_token},
    )
    assert resp.status_code == 200
    assert resp.json()["project_id"] == project_id


@pytest.mark.asyncio
async def test_detach_task_from_project(
    async_client: AsyncClient,
    user_token: str,
    seed_users,
    db_session: AsyncSession,
):
    resp = await async_client.patch(
        f"/tasks/{SEEDED_TASK_ID}/project",
        json={"project_id": None},
        headers={"Authorization": user_token},
    )
    assert resp.status_code == 200
    assert resp.json()["project_id"] is None
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /Users/admin/Desktop/смета\ аи/smeta-ai/backend
python -m pytest tests/test_task_file_slots.py -v
```

Expected: FAIL — 404/405 (endpoints not implemented)

- [ ] **Step 3: Add endpoints to tasks.py**

Add these imports at the top of `backend/app/routers/tasks.py` (after existing imports):

```python
from decimal import Decimal
from app.models.result import TaskResult
from app.models.project import Project
from app.constants import ESTIMATE_TASK_TYPES
from app.utils.xlsx_cost_parser import extract_total_cost
```

Add these Pydantic models after the existing ones in tasks.py:

```python
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
XLSX_MIME_ALT = "application/vnd.ms-excel"
VALID_SLOTS = {"source", "estimate", "optimized"}


class FileSlotResponse(BaseModel):
    task_id: str
    slot: str
    file_name: str
    estimation_status: Optional[str] = None
    cost: Optional[float] = None
    warning: Optional[str] = None


class EstimationConfirmRequest(BaseModel):
    estimation_status: str  # must be 'optimized'


class EstimationStatusResponse(BaseModel):
    task_id: str
    estimation_status: str


class ProjectLinkRequest(BaseModel):
    project_id: Optional[str] = None


class ProjectLinkResponse(BaseModel):
    task_id: str
    project_id: Optional[str]
```

Add these three endpoint functions at the end of `backend/app/routers/tasks.py`:

```python
@router.post("/{task_id}/files", response_model=FileSlotResponse)
async def upload_file_to_slot(
    task_id: str,
    slot: str = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Upload a file into a named slot (source / estimate / optimized)."""
    if slot not in VALID_SLOTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Недопустимый слот. Допустимые значения: {', '.join(VALID_SLOTS)}",
        )

    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")

    # Only xlsx allowed in estimate/optimized slots; source slot accepts xlsx too
    mime = _get_mime_type(file)
    if slot in ("estimate", "optimized", "source"):
        if mime not in (XLSX_MIME, XLSX_MIME_ALT):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Допустимый формат для файловых слотов: XLSX",
            )

    file_bytes = await file.read()

    # Delete existing record for this slot (replace semantics)
    existing = await db.execute(
        select(TaskResult).where(
            TaskResult.task_id == task_id, TaskResult.slot == slot
        )
    )
    old = existing.scalar_one_or_none()
    if old:
        await db.delete(old)

    # Create new TaskResult
    new_result = TaskResult(
        task_id=task_id,
        file_name=file.filename or f"{slot}.xlsx",
        mime_type=mime,
        file_data=file_bytes,
        slot=slot,
    )
    db.add(new_result)

    warning: Optional[str] = None

    # Parse cost when estimate slot
    if slot == "estimate" and task.task_type in ESTIMATE_TASK_TYPES:
        cost = extract_total_cost(file_bytes)
        if cost is not None:
            task.cost = cost
            task.estimation_status = "estimated"
        else:
            task.cost = None
            task.estimation_status = "unestimated"
            warning = "Строка 'Итого'/'Всего' не найдена или не содержит числового значения. Стоимость не определена."

    await db.commit()
    await db.refresh(task)

    return FileSlotResponse(
        task_id=task_id,
        slot=slot,
        file_name=file.filename or f"{slot}.xlsx",
        estimation_status=task.estimation_status,
        cost=float(task.cost) if task.cost is not None else None,
        warning=warning,
    )


@router.delete("/{task_id}/files/{slot}")
async def delete_file_from_slot(
    task_id: str,
    slot: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Delete a file from a named slot."""
    if slot not in VALID_SLOTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Недопустимый слот: {slot}",
        )

    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")

    existing = await db.execute(
        select(TaskResult).where(
            TaskResult.task_id == task_id, TaskResult.slot == slot
        )
    )
    row = existing.scalar_one_or_none()
    if row:
        await db.delete(row)

    # Reset estimation state when estimate slot cleared
    if slot == "estimate" and task.task_type in ESTIMATE_TASK_TYPES:
        task.cost = None
        task.estimation_status = "unestimated"

    await db.commit()
    return {"task_id": task_id, "slot": slot, "status": "deleted"}


@router.patch("/{task_id}/estimation", response_model=EstimationStatusResponse)
async def confirm_estimation(
    task_id: str,
    body: EstimationConfirmRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Confirm that the optimized file is the final version."""
    if body.estimation_status != "optimized":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Допустимое значение: 'optimized'",
        )

    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")

    # Verify optimized file exists
    slot_result = await db.execute(
        select(TaskResult).where(
            TaskResult.task_id == task_id, TaskResult.slot == "optimized"
        )
    )
    if slot_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Файл в слоте 'optimized' отсутствует. Загрузите файл перед подтверждением.",
        )

    task.estimation_status = "optimized"
    await db.commit()
    return EstimationStatusResponse(task_id=task_id, estimation_status="optimized")


@router.patch("/{task_id}/project", response_model=ProjectLinkResponse)
async def link_task_to_project(
    task_id: str,
    body: ProjectLinkRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Attach or detach a task from a project."""
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")

    if body.project_id is not None:
        proj_result = await db.execute(select(Project).where(Project.id == body.project_id))
        if proj_result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Проект не найден",
            )

    task.project_id = body.project_id
    await db.commit()
    return ProjectLinkResponse(task_id=task_id, project_id=body.project_id)
```

Also update `POST /tasks` to accept optional `project_id` and `project_name`. Add these two optional Form fields to the `create_task` endpoint signature (after `prompt`):

```python
project_id: Optional[str] = Form(None),
project_name: Optional[str] = Form(None),
```

And after `await db.refresh(task)`, before the logger.info call, add:

```python
    # Link to project (create new if project_name given)
    if project_name and not project_id:
        new_proj = Project(name=project_name)
        db.add(new_proj)
        await db.flush()
        task.project_id = str(new_proj.id)
        await db.commit()
        await db.refresh(task)
    elif project_id:
        proj_check = await db.execute(select(Project).where(Project.id == project_id))
        if proj_check.scalar_one_or_none():
            task.project_id = project_id
            await db.commit()
```

Also update `TaskStatusResponse` to include `estimation_status`, `cost`, and `project_id`:

```python
class TaskStatusResponse(BaseModel):
    id: str
    task_type: str
    status: str
    progress_message: Optional[str]
    error_message: Optional[str]
    estimation_status: str
    cost: Optional[float]
    project_id: Optional[str]
    created_at: str
    updated_at: str
```

And update `get_task_status` return value to include the new fields:

```python
    return TaskStatusResponse(
        id=str(task.id),
        task_type=task.task_type,
        status=task.status,
        progress_message=task.progress_message,
        error_message=task.error_message,
        estimation_status=task.estimation_status,
        cost=float(task.cost) if task.cost is not None else None,
        project_id=str(task.project_id) if task.project_id else None,
        created_at=task.created_at.isoformat(),
        updated_at=task.updated_at.isoformat(),
    )
```

Also update `task_processor.py` to set `estimation_status` when creating tasks. In the task creation in `task_processor.py` — actually this is done in `tasks.py` at creation time. Add this logic right before `db.add(task)` in `create_task`:

```python
    from app.constants import ESTIMATE_TASK_TYPES
    estimation_status = "unestimated" if task_type in ESTIMATE_TASK_TYPES else "not_applicable"

    task = Task(
        user_role=current_user.get("role", "user"),
        task_type=task_type,
        status="pending",
        input_files=input_files_meta,
        input_file_data=input_file_data,
        user_prompt=prompt,
        chat_history=[],
        estimation_status=estimation_status,
    )
```

- [ ] **Step 4: Run tests**

```bash
cd /Users/admin/Desktop/смета\ аи/smeta-ai/backend
python -m pytest tests/test_task_file_slots.py -v
```

Expected: all 9 tests PASS

- [ ] **Step 5: Run all backend tests**

```bash
cd /Users/admin/Desktop/смета\ аи/smeta-ai/backend
python -m pytest tests/ -v
```

Expected: all tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/tasks.py backend/tests/test_task_file_slots.py
git commit -m "feat: file slot endpoints + estimation confirmation + project linking on tasks"
```

---

### Task 7: Frontend types

**Files:**
- Modify: `frontend/src/types/index.ts`

- [ ] **Step 1: Update types/index.ts**

Replace the full contents:

```typescript
// frontend/src/types/index.ts
export type TaskType =
  | 'LIST_FROM_TZ'
  | 'LIST_FROM_TZ_PROJECT'
  | 'RESEARCH_PROJECT'
  | 'LIST_FROM_PROJECT'
  | 'SMETA_FROM_GRAND_PROJECT'
  | 'SMETA_FROM_PROJECT'
  | 'SMETA_FROM_EDC_PROJECT'
  | 'SMETA_FROM_LIST'
  | 'SCAN_TO_EXCEL'
  | 'COMPARE_PROJECT_SMETA';

export type TaskStatus = 'pending' | 'processing' | 'completed' | 'failed' | 'cancelled';

export type EstimationStatus = 'unestimated' | 'estimated' | 'optimized' | 'not_applicable';

export const ESTIMATE_TASK_TYPES: Set<TaskType> = new Set([
  'SMETA_FROM_LIST',
  'SMETA_FROM_PROJECT',
  'SMETA_FROM_EDC_PROJECT',
  'SMETA_FROM_GRAND_PROJECT',
  'SCAN_TO_EXCEL',
]);

export interface Task {
  id: string;
  task_type: TaskType;
  status: TaskStatus;
  user_prompt?: string;
  progress_message?: string;
  error_message?: string;
  estimation_status: EstimationStatus;
  cost?: number | null;
  project_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface TaskResult {
  file_id: number;
  file_name: string;
  mime_type: string;
  slot: string;
}

export interface AdminTask extends Task {
  user_role: string;
  input_files: Array<{ name: string; mime_type: string; size_bytes: number }>;
  chat_history: Array<{ role: string; content: string; timestamp: string }>;
  results?: TaskResult[];
}

export interface AdminTasksParams {
  page?: number;
  page_size?: number;
  status?: TaskStatus;
  task_type?: TaskType;
  date_from?: string;
  date_to?: string;
}

export interface AdminTasksResponse {
  items: AdminTask[];
  total: number;
  page: number;
  page_size: number;
}

export const TASK_TYPE_LABELS: Record<TaskType, string> = {
  LIST_FROM_TZ: 'Перечень из ТЗ',
  LIST_FROM_TZ_PROJECT: 'Перечень из ТЗ + Проект',
  RESEARCH_PROJECT: 'Проверка проектной документации',
  LIST_FROM_PROJECT: 'Перечень из Проекта',
  SMETA_FROM_GRAND_PROJECT: 'Смета: ГРАНД-смета + Проект',
  SMETA_FROM_PROJECT: 'Смета из Проекта',
  SMETA_FROM_EDC_PROJECT: 'Смета: ЭДЦ + Проект',
  SMETA_FROM_LIST: 'Смета из перечня',
  SCAN_TO_EXCEL: 'Скан сметы → Excel',
  COMPARE_PROJECT_SMETA: 'Сравнение проект/смета',
};

export const STATUS_LABELS: Record<TaskStatus, string> = {
  pending: 'Ожидание',
  processing: 'Обработка',
  completed: 'Завершено',
  failed: 'Ошибка',
  cancelled: 'Остановлено',
};

export interface Project {
  id: string;
  name: string;
  description?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProjectCard extends Project {
  unestimated: number;
  estimated: number;
  optimized: number;
  other: number;
  total_cost: number | null;
}

export interface TaskBrief {
  id: string;
  task_type: string;
  status: string;
  estimation_status: EstimationStatus;
  cost: number | null;
  created_at: string;
}

export interface ProjectDetail extends ProjectCard {
  tasks: TaskBrief[];
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/types/index.ts
git commit -m "feat: add Project/ProjectCard/ProjectDetail types + EstimationStatus + ESTIMATE_TASK_TYPES"
```

---

### Task 8: Frontend API — projects

**Files:**
- Create: `frontend/src/api/projects.ts`

- [ ] **Step 1: Create projects.ts**

```typescript
// frontend/src/api/projects.ts
import apiClient from './client';
import { Project, ProjectCard, ProjectDetail } from '../types';

export interface ProjectCreatePayload {
  name: string;
  description?: string;
}

export interface ProjectUpdatePayload {
  name?: string;
  description?: string;
}

export async function listProjects(): Promise<ProjectCard[]> {
  const resp = await apiClient.get<ProjectCard[]>('/projects');
  return resp.data;
}

export async function getProject(projectId: string): Promise<ProjectDetail> {
  const resp = await apiClient.get<ProjectDetail>(`/projects/${projectId}`);
  return resp.data;
}

export async function createProject(payload: ProjectCreatePayload): Promise<Project> {
  const resp = await apiClient.post<Project>('/projects', payload);
  return resp.data;
}

export async function updateProject(projectId: string, payload: ProjectUpdatePayload): Promise<Project> {
  const resp = await apiClient.patch<Project>(`/projects/${projectId}`, payload);
  return resp.data;
}

export async function deleteProject(projectId: string): Promise<void> {
  await apiClient.delete(`/projects/${projectId}`);
}

export async function uploadFileToSlot(
  taskId: string,
  slot: 'source' | 'estimate' | 'optimized',
  file: File,
): Promise<{ slot: string; estimation_status?: string; cost?: number | null; warning?: string }> {
  const form = new FormData();
  form.append('slot', slot);
  form.append('file', file);
  const resp = await apiClient.post(`/tasks/${taskId}/files`, form);
  return resp.data;
}

export async function deleteFileFromSlot(
  taskId: string,
  slot: 'source' | 'estimate' | 'optimized',
): Promise<void> {
  await apiClient.delete(`/tasks/${taskId}/files/${slot}`);
}

export async function confirmOptimized(taskId: string): Promise<{ estimation_status: string }> {
  const resp = await apiClient.patch<{ estimation_status: string }>(
    `/tasks/${taskId}/estimation`,
    { estimation_status: 'optimized' },
  );
  return resp.data;
}

export async function linkTaskToProject(
  taskId: string,
  projectId: string | null,
): Promise<{ project_id: string | null }> {
  const resp = await apiClient.patch<{ project_id: string | null }>(
    `/tasks/${taskId}/project`,
    { project_id: projectId },
  );
  return resp.data;
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/api/projects.ts
git commit -m "feat: projects API client functions"
```

---

### Task 9: Projects list page

**Files:**
- Create: `frontend/src/pages/Projects.tsx`

- [ ] **Step 1: Create Projects.tsx**

```tsx
// frontend/src/pages/Projects.tsx
import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import Layout from '../components/Layout';
import { ProjectCard } from '../types';
import { listProjects, createProject } from '../api/projects';

function formatCost(cost: number | null): string {
  if (cost === null || cost === undefined) return '—';
  return new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'RUB', maximumFractionDigits: 0 }).format(cost);
}

const Projects: React.FC = () => {
  const navigate = useNavigate();
  const [projects, setProjects] = useState<ProjectCard[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState('');
  const [newDesc, setNewDesc] = useState('');
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    loadProjects();
  }, []);

  async function loadProjects() {
    setLoading(true);
    try {
      const data = await listProjects();
      setProjects(data);
    } catch {
      setError('Ошибка при загрузке проектов');
    } finally {
      setLoading(false);
    }
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!newName.trim()) return;
    setCreating(true);
    try {
      await createProject({ name: newName.trim(), description: newDesc.trim() || undefined });
      setNewName('');
      setNewDesc('');
      setShowCreate(false);
      await loadProjects();
    } catch {
      setError('Ошибка при создании проекта');
    } finally {
      setCreating(false);
    }
  }

  return (
    <Layout>
      <div style={{ maxWidth: '900px', margin: '0 auto' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
          <h1 style={{ fontSize: '24px', fontWeight: 700, color: '#1e293b', margin: 0 }}>Проекты</h1>
          <button
            onClick={() => setShowCreate(!showCreate)}
            style={{
              padding: '8px 18px',
              backgroundColor: '#2563eb',
              color: '#fff',
              border: 'none',
              borderRadius: '8px',
              cursor: 'pointer',
              fontSize: '14px',
              fontWeight: 600,
            }}
          >
            + Новый проект
          </button>
        </div>

        {showCreate && (
          <form
            onSubmit={handleCreate}
            style={{
              backgroundColor: '#fff',
              border: '1px solid #e2e8f0',
              borderRadius: '12px',
              padding: '20px',
              marginBottom: '24px',
            }}
          >
            <h3 style={{ margin: '0 0 16px', fontSize: '16px', fontWeight: 600 }}>Новый проект</h3>
            <input
              type="text"
              placeholder="Название проекта *"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              required
              style={{
                width: '100%',
                padding: '10px 12px',
                border: '1px solid #e2e8f0',
                borderRadius: '8px',
                fontSize: '14px',
                marginBottom: '12px',
                boxSizing: 'border-box',
              }}
            />
            <textarea
              placeholder="Описание (необязательно)"
              value={newDesc}
              onChange={(e) => setNewDesc(e.target.value)}
              rows={3}
              style={{
                width: '100%',
                padding: '10px 12px',
                border: '1px solid #e2e8f0',
                borderRadius: '8px',
                fontSize: '14px',
                marginBottom: '12px',
                resize: 'vertical',
                boxSizing: 'border-box',
              }}
            />
            <div style={{ display: 'flex', gap: '8px' }}>
              <button
                type="submit"
                disabled={creating}
                style={{
                  padding: '8px 18px',
                  backgroundColor: '#2563eb',
                  color: '#fff',
                  border: 'none',
                  borderRadius: '8px',
                  cursor: creating ? 'not-allowed' : 'pointer',
                  fontSize: '14px',
                  fontWeight: 600,
                }}
              >
                {creating ? 'Создание...' : 'Создать'}
              </button>
              <button
                type="button"
                onClick={() => setShowCreate(false)}
                style={{
                  padding: '8px 18px',
                  backgroundColor: 'transparent',
                  color: '#64748b',
                  border: '1px solid #e2e8f0',
                  borderRadius: '8px',
                  cursor: 'pointer',
                  fontSize: '14px',
                }}
              >
                Отмена
              </button>
            </div>
          </form>
        )}

        {error && (
          <div style={{ padding: '12px', backgroundColor: '#fef2f2', color: '#dc2626', borderRadius: '8px', marginBottom: '16px' }}>
            {error}
          </div>
        )}

        {loading ? (
          <div style={{ textAlign: 'center', color: '#94a3b8', padding: '48px' }}>Загрузка...</div>
        ) : projects.length === 0 ? (
          <div style={{ textAlign: 'center', color: '#94a3b8', padding: '48px', backgroundColor: '#fff', borderRadius: '12px', border: '1px solid #e2e8f0' }}>
            Проекты не найдены. Создайте первый проект.
          </div>
        ) : (
          <div style={{ display: 'grid', gap: '16px' }}>
            {projects.map((p) => (
              <div
                key={p.id}
                onClick={() => navigate(`/projects/${p.id}`)}
                style={{
                  backgroundColor: '#fff',
                  border: '1px solid #e2e8f0',
                  borderRadius: '12px',
                  padding: '20px 24px',
                  cursor: 'pointer',
                  transition: 'box-shadow 0.15s',
                }}
                onMouseEnter={(e) => (e.currentTarget.style.boxShadow = '0 4px 12px rgba(0,0,0,0.08)')}
                onMouseLeave={(e) => (e.currentTarget.style.boxShadow = 'none')}
              >
                <h2 style={{ margin: '0 0 6px', fontSize: '18px', fontWeight: 600, color: '#1e293b' }}>{p.name}</h2>
                {p.description && (
                  <p style={{ margin: '0 0 16px', fontSize: '14px', color: '#64748b' }}>{p.description}</p>
                )}

                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px', marginTop: '12px' }}>
                  {p.unestimated > 0 && (
                    <span style={{ padding: '4px 12px', backgroundColor: '#fef2f2', color: '#dc2626', borderRadius: '20px', fontSize: '13px', fontWeight: 500 }}>
                      {p.unestimated} не рассчитано
                    </span>
                  )}
                  {p.estimated > 0 && (
                    <span style={{ padding: '4px 12px', backgroundColor: '#fef9c3', color: '#854d0e', borderRadius: '20px', fontSize: '13px', fontWeight: 500 }}>
                      {p.estimated} рассчитано {p.total_cost !== null ? `· ${formatCost(p.total_cost)}` : ''}
                    </span>
                  )}
                  {p.optimized > 0 && (
                    <span style={{ padding: '4px 12px', backgroundColor: '#f0fdf4', color: '#15803d', borderRadius: '20px', fontSize: '13px', fontWeight: 500 }}>
                      {p.optimized} оптимизировано
                    </span>
                  )}
                  {p.other > 0 && (
                    <span style={{ padding: '4px 12px', backgroundColor: '#f8fafc', color: '#64748b', borderRadius: '20px', fontSize: '13px', fontWeight: 500 }}>
                      {p.other} прочих задач
                    </span>
                  )}
                  {p.unestimated === 0 && p.estimated === 0 && p.optimized === 0 && p.other === 0 && (
                    <span style={{ fontSize: '13px', color: '#94a3b8' }}>Задач нет</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </Layout>
  );
};

export default Projects;
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/Projects.tsx
git commit -m "feat: Projects list page with cards and aggregation badges"
```

---

### Task 10: Project detail page

**Files:**
- Create: `frontend/src/pages/ProjectDetail.tsx`

- [ ] **Step 1: Create ProjectDetail.tsx**

```tsx
// frontend/src/pages/ProjectDetail.tsx
import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import Layout from '../components/Layout';
import { ProjectDetail as IProjectDetail, TaskBrief, TASK_TYPE_LABELS } from '../types';
import { getProject, updateProject, deleteProject } from '../api/projects';
import { useAuthStore } from '../stores/auth';

const ESTIMATION_LABELS: Record<string, string> = {
  unestimated: 'Не рассчитано',
  estimated: 'Рассчитано',
  optimized: 'Оптимизировано',
  not_applicable: '—',
};

const ESTIMATION_COLORS: Record<string, { bg: string; text: string }> = {
  unestimated: { bg: '#fef2f2', text: '#dc2626' },
  estimated: { bg: '#fef9c3', text: '#854d0e' },
  optimized: { bg: '#f0fdf4', text: '#15803d' },
  not_applicable: { bg: '#f8fafc', text: '#94a3b8' },
};

function formatCost(cost: number | null): string {
  if (cost === null || cost === undefined) return '—';
  return new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'RUB', maximumFractionDigits: 0 }).format(cost);
}

const ProjectDetailPage: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const { isAdmin } = useAuthStore();

  const [project, setProject] = useState<IProjectDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [editing, setEditing] = useState(false);
  const [editName, setEditName] = useState('');
  const [editDesc, setEditDesc] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (projectId) loadProject();
  }, [projectId]);

  async function loadProject() {
    setLoading(true);
    try {
      const data = await getProject(projectId!);
      setProject(data);
      setEditName(data.name);
      setEditDesc(data.description ?? '');
    } catch {
      setError('Проект не найден');
    } finally {
      setLoading(false);
    }
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    if (!editName.trim() || !projectId) return;
    setSaving(true);
    try {
      const updated = await updateProject(projectId, {
        name: editName.trim(),
        description: editDesc.trim() || undefined,
      });
      setProject((prev) => prev ? { ...prev, name: updated.name, description: updated.description } : prev);
      setEditing(false);
    } catch {
      setError('Ошибка при сохранении');
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!projectId) return;
    if (!window.confirm('Удалить проект? Задачи останутся, но будут откреплены.')) return;
    try {
      await deleteProject(projectId);
      navigate('/projects');
    } catch {
      setError('Ошибка при удалении проекта');
    }
  }

  if (loading) {
    return <Layout><div style={{ textAlign: 'center', padding: '48px', color: '#94a3b8' }}>Загрузка...</div></Layout>;
  }

  if (error || !project) {
    return (
      <Layout>
        <div style={{ textAlign: 'center', padding: '48px', color: '#dc2626' }}>{error || 'Проект не найден'}</div>
      </Layout>
    );
  }

  return (
    <Layout>
      <div style={{ maxWidth: '900px', margin: '0 auto' }}>
        {/* Back */}
        <button
          onClick={() => navigate('/projects')}
          style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#2563eb', fontSize: '14px', marginBottom: '16px', padding: 0 }}
        >
          ← Все проекты
        </button>

        {/* Header card */}
        <div style={{ backgroundColor: '#fff', border: '1px solid #e2e8f0', borderRadius: '12px', padding: '24px', marginBottom: '24px' }}>
          {editing ? (
            <form onSubmit={handleSave}>
              <input
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                required
                style={{ width: '100%', padding: '10px 12px', border: '1px solid #e2e8f0', borderRadius: '8px', fontSize: '18px', fontWeight: 600, marginBottom: '12px', boxSizing: 'border-box' }}
              />
              <textarea
                value={editDesc}
                onChange={(e) => setEditDesc(e.target.value)}
                rows={3}
                style={{ width: '100%', padding: '10px 12px', border: '1px solid #e2e8f0', borderRadius: '8px', fontSize: '14px', marginBottom: '12px', resize: 'vertical', boxSizing: 'border-box' }}
              />
              <div style={{ display: 'flex', gap: '8px' }}>
                <button type="submit" disabled={saving} style={{ padding: '8px 18px', backgroundColor: '#2563eb', color: '#fff', border: 'none', borderRadius: '8px', cursor: 'pointer', fontWeight: 600, fontSize: '14px' }}>
                  {saving ? 'Сохранение...' : 'Сохранить'}
                </button>
                <button type="button" onClick={() => setEditing(false)} style={{ padding: '8px 18px', backgroundColor: 'transparent', color: '#64748b', border: '1px solid #e2e8f0', borderRadius: '8px', cursor: 'pointer', fontSize: '14px' }}>
                  Отмена
                </button>
              </div>
            </form>
          ) : (
            <>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div>
                  <h1 style={{ margin: '0 0 8px', fontSize: '22px', fontWeight: 700, color: '#1e293b' }}>{project.name}</h1>
                  {project.description && <p style={{ margin: 0, fontSize: '14px', color: '#64748b' }}>{project.description}</p>}
                </div>
                <div style={{ display: 'flex', gap: '8px' }}>
                  <button onClick={() => setEditing(true)} style={{ padding: '7px 14px', backgroundColor: 'transparent', border: '1px solid #e2e8f0', borderRadius: '8px', cursor: 'pointer', fontSize: '13px', color: '#64748b' }}>
                    Изменить
                  </button>
                  {isAdmin && (
                    <button onClick={handleDelete} style={{ padding: '7px 14px', backgroundColor: '#fee2e2', border: 'none', borderRadius: '8px', cursor: 'pointer', fontSize: '13px', color: '#dc2626', fontWeight: 500 }}>
                      Удалить
                    </button>
                  )}
                </div>
              </div>

              {/* Aggregation badges */}
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px', marginTop: '16px' }}>
                {project.unestimated > 0 && (
                  <span style={{ padding: '4px 12px', backgroundColor: '#fef2f2', color: '#dc2626', borderRadius: '20px', fontSize: '13px', fontWeight: 500 }}>
                    {project.unestimated} не рассчитано
                  </span>
                )}
                {project.estimated > 0 && (
                  <span style={{ padding: '4px 12px', backgroundColor: '#fef9c3', color: '#854d0e', borderRadius: '20px', fontSize: '13px', fontWeight: 500 }}>
                    {project.estimated} рассчитано · {formatCost(project.total_cost)}
                  </span>
                )}
                {project.optimized > 0 && (
                  <span style={{ padding: '4px 12px', backgroundColor: '#f0fdf4', color: '#15803d', borderRadius: '20px', fontSize: '13px', fontWeight: 500 }}>
                    {project.optimized} оптимизировано
                  </span>
                )}
                {project.other > 0 && (
                  <span style={{ padding: '4px 12px', backgroundColor: '#f8fafc', color: '#64748b', borderRadius: '20px', fontSize: '13px', fontWeight: 500 }}>
                    {project.other} прочих задач
                  </span>
                )}
              </div>
            </>
          )}
        </div>

        {/* Tasks list */}
        <h2 style={{ fontSize: '16px', fontWeight: 600, color: '#1e293b', marginBottom: '12px' }}>
          Задачи ({project.tasks.length})
        </h2>

        {project.tasks.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '32px', backgroundColor: '#fff', borderRadius: '12px', border: '1px solid #e2e8f0', color: '#94a3b8', fontSize: '14px' }}>
            Задач в проекте пока нет
          </div>
        ) : (
          <div style={{ display: 'grid', gap: '8px' }}>
            {project.tasks.map((task: TaskBrief) => {
              const estColors = ESTIMATION_COLORS[task.estimation_status] ?? ESTIMATION_COLORS.not_applicable;
              return (
                <div
                  key={task.id}
                  onClick={() => navigate(`/task/${task.id}/status`)}
                  style={{
                    backgroundColor: '#fff',
                    border: '1px solid #e2e8f0',
                    borderRadius: '10px',
                    padding: '14px 18px',
                    cursor: 'pointer',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.boxShadow = '0 2px 8px rgba(0,0,0,0.06)')}
                  onMouseLeave={(e) => (e.currentTarget.style.boxShadow = 'none')}
                >
                  <div>
                    <div style={{ fontSize: '14px', fontWeight: 600, color: '#1e293b' }}>
                      {TASK_TYPE_LABELS[task.task_type as keyof typeof TASK_TYPE_LABELS] ?? task.task_type}
                    </div>
                    <div style={{ fontSize: '12px', color: '#94a3b8', marginTop: '2px' }}>
                      {new Date(task.created_at).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })}
                    </div>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    {task.cost !== null && (
                      <span style={{ fontSize: '14px', fontWeight: 600, color: '#1e293b' }}>{formatCost(task.cost)}</span>
                    )}
                    {task.estimation_status !== 'not_applicable' && (
                      <span style={{ padding: '3px 10px', backgroundColor: estColors.bg, color: estColors.text, borderRadius: '12px', fontSize: '12px', fontWeight: 500 }}>
                        {ESTIMATION_LABELS[task.estimation_status]}
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </Layout>
  );
};

export default ProjectDetailPage;
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/ProjectDetail.tsx
git commit -m "feat: ProjectDetail page with task list and inline editing"
```

---

### Task 11: Frontend routes

**Files:**
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Update App.tsx**

Replace the full contents of `frontend/src/App.tsx`:

```tsx
import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import ProtectedRoute from './components/ProtectedRoute';
import Login from './pages/Login';
import TaskCreate from './pages/TaskCreate';
import TaskStatus from './pages/TaskStatus';
import Admin from './pages/Admin';
import Projects from './pages/Projects';
import ProjectDetail from './pages/ProjectDetail';
import { useAuthStore } from './stores/auth';

const App: React.FC = () => {
  const { isAuthenticated, isAdmin } = useAuthStore();

  return (
    <BrowserRouter>
      <Routes>
        {/* Public route */}
        <Route
          path="/login"
          element={
            isAuthenticated ? (
              <Navigate to={isAdmin ? '/admin' : '/task/create'} replace />
            ) : (
              <Login />
            )
          }
        />

        {/* Protected user routes */}
        <Route
          path="/task/create"
          element={
            <ProtectedRoute>
              <TaskCreate />
            </ProtectedRoute>
          }
        />
        <Route
          path="/task/:taskId/status"
          element={
            <ProtectedRoute>
              <TaskStatus />
            </ProtectedRoute>
          }
        />
        <Route
          path="/projects"
          element={
            <ProtectedRoute>
              <Projects />
            </ProtectedRoute>
          }
        />
        <Route
          path="/projects/:projectId"
          element={
            <ProtectedRoute>
              <ProjectDetail />
            </ProtectedRoute>
          }
        />

        {/* Protected admin routes */}
        <Route
          path="/admin"
          element={
            <ProtectedRoute requireAdmin>
              <Admin />
            </ProtectedRoute>
          }
        />

        {/* Default redirect */}
        <Route
          path="/"
          element={
            <Navigate
              to={isAuthenticated ? (isAdmin ? '/admin' : '/task/create') : '/login'}
              replace
            />
          }
        />

        {/* Catch-all redirect */}
        <Route
          path="*"
          element={
            <Navigate
              to={isAuthenticated ? (isAdmin ? '/admin' : '/task/create') : '/login'}
              replace
            />
          }
        />
      </Routes>
    </BrowserRouter>
  );
};

export default App;
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "feat: add /projects and /projects/:projectId routes"
```

---

### Task 12: Layout nav button

**Files:**
- Modify: `frontend/src/components/Layout.tsx`

- [ ] **Step 1: Add "Проекты" button to Layout.tsx**

In the nav buttons section (inside the `<div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>` at lines 65–115), add the "Проекты" button before the logout button. The updated nav div:

```tsx
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          {isAdmin && (
            <button
              onClick={() => navigate('/admin')}
              style={{
                padding: '7px 16px',
                backgroundColor: 'transparent',
                color: '#64748b',
                border: '1px solid #e2e8f0',
                borderRadius: '8px',
                cursor: 'pointer',
                fontSize: '14px',
                fontWeight: 500,
              }}
            >
              Панель администратора
            </button>
          )}
          {isAdmin && (
            <button
              onClick={() => navigate('/task/create')}
              style={{
                padding: '7px 16px',
                backgroundColor: 'transparent',
                color: '#64748b',
                border: '1px solid #e2e8f0',
                borderRadius: '8px',
                cursor: 'pointer',
                fontSize: '14px',
                fontWeight: 500,
              }}
            >
              Создать задачу
            </button>
          )}
          <button
            onClick={() => navigate('/projects')}
            style={{
              padding: '7px 16px',
              backgroundColor: 'transparent',
              color: '#64748b',
              border: '1px solid #e2e8f0',
              borderRadius: '8px',
              cursor: 'pointer',
              fontSize: '14px',
              fontWeight: 500,
            }}
          >
            Проекты
          </button>
          <button
            onClick={handleLogout}
            style={{
              padding: '7px 16px',
              backgroundColor: '#fee2e2',
              color: '#dc2626',
              border: 'none',
              borderRadius: '8px',
              cursor: 'pointer',
              fontSize: '14px',
              fontWeight: 500,
            }}
          >
            Выйти
          </button>
        </div>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/Layout.tsx
git commit -m "feat: add Проекты nav button to Layout header"
```

---

### Task 13: TaskCreate — project selector

**Files:**
- Modify: `frontend/src/pages/TaskCreate.tsx`

- [ ] **Step 1: Add project selector to TaskCreate.tsx**

At the top of the file, add these imports after the existing imports:

```tsx
import { listProjects } from '../api/projects';
import { ProjectCard } from '../types';
```

Add these state variables inside `TaskCreate` component (after existing state):

```tsx
  const [projects, setProjects] = useState<ProjectCard[]>([]);
  const [projectMode, setProjectMode] = useState<'none' | 'existing' | 'new'>('none');
  const [selectedProjectId, setSelectedProjectId] = useState('');
  const [newProjectName, setNewProjectName] = useState('');
```

Add a `useEffect` to load projects:

```tsx
  useEffect(() => {
    listProjects().then(setProjects).catch(() => {});
  }, []);
```

In `handleSubmit`, when building `formData` (before `createTask`), add:

```tsx
      if (projectMode === 'existing' && selectedProjectId) {
        formData.append('project_id', selectedProjectId);
      } else if (projectMode === 'new' && newProjectName.trim()) {
        formData.append('project_name', newProjectName.trim());
      }
```

Add the project selector block at the bottom of the form (before the submit button section). Insert after the prompt textarea section, before the submit button:

```tsx
        {/* Project selector */}
        <div style={{ marginBottom: '24px' }}>
          <label style={{ display: 'block', fontSize: '14px', fontWeight: 600, color: '#374151', marginBottom: '10px' }}>
            Добавить в проект
          </label>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {(['none', 'existing', 'new'] as const).map((mode) => (
              <label key={mode} style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
                <input
                  type="radio"
                  name="projectMode"
                  value={mode}
                  checked={projectMode === mode}
                  onChange={() => setProjectMode(mode)}
                />
                <span style={{ fontSize: '14px', color: '#374151' }}>
                  {mode === 'none' ? 'Не добавлять' : mode === 'existing' ? 'Выбрать существующий' : 'Создать новый'}
                </span>
              </label>
            ))}
          </div>

          {projectMode === 'existing' && (
            <select
              value={selectedProjectId}
              onChange={(e) => setSelectedProjectId(e.target.value)}
              style={{
                marginTop: '12px',
                width: '100%',
                padding: '10px 12px',
                border: '1px solid #e2e8f0',
                borderRadius: '8px',
                fontSize: '14px',
                backgroundColor: '#fff',
              }}
            >
              <option value="">— Выберите проект —</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          )}

          {projectMode === 'new' && (
            <input
              type="text"
              placeholder="Название нового проекта"
              value={newProjectName}
              onChange={(e) => setNewProjectName(e.target.value)}
              style={{
                marginTop: '12px',
                width: '100%',
                padding: '10px 12px',
                border: '1px solid #e2e8f0',
                borderRadius: '8px',
                fontSize: '14px',
                boxSizing: 'border-box',
              }}
            />
          )}
        </div>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/TaskCreate.tsx
git commit -m "feat: project selector block in TaskCreate form"
```

---

### Task 14: TaskStatus — file slots + estimation badge + attach to project

**Files:**
- Modify: `frontend/src/pages/TaskStatus.tsx`
- Modify: `frontend/src/api/tasks.ts`

- [ ] **Step 1: Update tasks.ts — add estimation fields to TaskStatusResponse**

In `frontend/src/api/tasks.ts`, update `TaskStatusResponse`:

```typescript
export interface TaskStatusResponse {
  id: string;
  status: Task['status'];
  task_type: Task['task_type'];
  progress_message?: string;
  error_message?: string;
  estimation_status: string;
  cost?: number | null;
  project_id?: string | null;
  created_at: string;
  updated_at: string;
}
```

- [ ] **Step 2: Add file slot + project UI to TaskStatus.tsx**

At the top of `frontend/src/pages/TaskStatus.tsx`, add imports:

```tsx
import { ESTIMATE_TASK_TYPES } from '../types';
import {
  uploadFileToSlot,
  deleteFileFromSlot,
  confirmOptimized,
  linkTaskToProject,
  listProjects,
} from '../api/projects';
import { ProjectCard } from '../types';
```

Add state inside `TaskStatusPage`:

```tsx
  const [slotUploading, setSlotUploading] = useState<string | null>(null);
  const [slotFiles, setSlotFiles] = useState<Record<string, { file_name: string; file_id?: number } | null>>({
    source: null,
    estimate: null,
    optimized: null,
  });
  const [estimationStatus, setEstimationStatus] = useState<string>('not_applicable');
  const [taskCost, setTaskCost] = useState<number | null>(null);
  const [taskProjectId, setTaskProjectId] = useState<string | null>(null);
  const [projects, setProjects] = useState<ProjectCard[]>([]);
  const [attachingProject, setAttachingProject] = useState(false);
  const [selectedAttachProjectId, setSelectedAttachProjectId] = useState('');
  const [slotWarning, setSlotWarning] = useState('');
```

After the `fetchStatus` function loads task data, sync state (inside the callback where `setTask` is called — add these lines right after `setTask(data)`):

```tsx
        setEstimationStatus(data.estimation_status ?? 'not_applicable');
        setTaskCost(data.cost ?? null);
        setTaskProjectId(data.project_id ?? null);
```

Also load projects list once (add a `useEffect`):

```tsx
  useEffect(() => {
    listProjects().then(setProjects).catch(() => {});
  }, []);
```

Add the slot upload handler:

```tsx
  async function handleSlotUpload(slot: 'source' | 'estimate' | 'optimized', file: File) {
    if (!taskId) return;
    setSlotUploading(slot);
    setSlotWarning('');
    try {
      const result = await uploadFileToSlot(taskId, slot, file);
      setSlotFiles((prev) => ({ ...prev, [slot]: { file_name: file.name } }));
      if (result.estimation_status) setEstimationStatus(result.estimation_status);
      if (result.cost !== undefined) setTaskCost(result.cost ?? null);
      if (result.warning) setSlotWarning(result.warning);
    } catch {
      setError('Ошибка при загрузке файла в слот');
    } finally {
      setSlotUploading(null);
    }
  }

  async function handleSlotDelete(slot: 'source' | 'estimate' | 'optimized') {
    if (!taskId) return;
    try {
      await deleteFileFromSlot(taskId, slot);
      setSlotFiles((prev) => ({ ...prev, [slot]: null }));
      if (slot === 'estimate') {
        setEstimationStatus('unestimated');
        setTaskCost(null);
      }
    } catch {
      setError('Ошибка при удалении файла');
    }
  }

  async function handleConfirmOptimized() {
    if (!taskId) return;
    try {
      const result = await confirmOptimized(taskId);
      setEstimationStatus(result.estimation_status);
    } catch {
      setError('Файл в слоте "Оптимизированный" отсутствует');
    }
  }

  async function handleAttachProject() {
    if (!taskId || !selectedAttachProjectId) return;
    try {
      await linkTaskToProject(taskId, selectedAttachProjectId);
      setTaskProjectId(selectedAttachProjectId);
      setAttachingProject(false);
    } catch {
      setError('Ошибка при прикреплении к проекту');
    }
  }
```

Find in TaskStatus.tsx the section where results are displayed (after the status card). Add the file slots section and estimation badge as a new card. Insert this block right before the existing "results" section (which shows download links):

```tsx
        {/* Estimation status badge */}
        {task && estimationStatus !== 'not_applicable' && (
          <div style={{ marginBottom: '16px' }}>
            <span style={{
              display: 'inline-block',
              padding: '5px 14px',
              borderRadius: '20px',
              fontSize: '13px',
              fontWeight: 600,
              ...({
                unestimated: { backgroundColor: '#fef2f2', color: '#dc2626' },
                estimated: { backgroundColor: '#fef9c3', color: '#854d0e' },
                optimized: { backgroundColor: '#f0fdf4', color: '#15803d' },
              }[estimationStatus] ?? { backgroundColor: '#f8fafc', color: '#94a3b8' }),
            }}>
              {{
                unestimated: 'Смета: не рассчитана',
                estimated: `Смета: рассчитана${taskCost !== null ? ` · ${new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'RUB', maximumFractionDigits: 0 }).format(taskCost)}` : ''}`,
                optimized: `Смета: оптимизирована${taskCost !== null ? ` · ${new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'RUB', maximumFractionDigits: 0 }).format(taskCost)}` : ''}`,
              }[estimationStatus] ?? estimationStatus}
            </span>
          </div>
        )}

        {/* File slots (only for ESTIMATE_TASK_TYPES) */}
        {task && ESTIMATE_TASK_TYPES.has(task.task_type) && (
          <div style={{ backgroundColor: '#fff', border: '1px solid #e2e8f0', borderRadius: '12px', padding: '20px', marginBottom: '16px' }}>
            <h3 style={{ margin: '0 0 16px', fontSize: '15px', fontWeight: 600, color: '#1e293b' }}>Файловые слоты</h3>

            {slotWarning && (
              <div style={{ padding: '10px 14px', backgroundColor: '#fef9c3', color: '#854d0e', borderRadius: '8px', fontSize: '13px', marginBottom: '12px' }}>
                {slotWarning}
              </div>
            )}

            {(['source', 'estimate', 'optimized'] as const).map((slot) => {
              const labels: Record<string, string> = {
                source: 'Исходный файл',
                estimate: 'Расчёт (смета)',
                optimized: 'Оптимизированный',
              };
              const fileInfo = slotFiles[slot];
              const isLoading = slotUploading === slot;

              return (
                <div key={slot} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 0', borderBottom: slot !== 'optimized' ? '1px solid #f1f5f9' : 'none' }}>
                  <span style={{ fontSize: '14px', color: '#374151', fontWeight: 500, minWidth: '160px' }}>{labels[slot]}</span>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    {fileInfo ? (
                      <>
                        <span style={{ fontSize: '13px', color: '#64748b' }}>{fileInfo.file_name}</span>
                        <button
                          onClick={() => handleSlotDelete(slot)}
                          style={{ padding: '3px 10px', backgroundColor: '#fee2e2', color: '#dc2626', border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '12px' }}
                        >
                          Удалить
                        </button>
                        {slot === 'optimized' && estimationStatus !== 'optimized' && (
                          <button
                            onClick={handleConfirmOptimized}
                            style={{ padding: '3px 10px', backgroundColor: '#f0fdf4', color: '#15803d', border: '1px solid #86efac', borderRadius: '6px', cursor: 'pointer', fontSize: '12px', fontWeight: 600 }}
                          >
                            Подтвердить
                          </button>
                        )}
                      </>
                    ) : (
                      <label style={{ cursor: isLoading ? 'not-allowed' : 'pointer' }}>
                        <input
                          type="file"
                          accept=".xlsx,.xls"
                          style={{ display: 'none' }}
                          disabled={isLoading}
                          onChange={(e) => {
                            const f = e.target.files?.[0];
                            if (f) handleSlotUpload(slot, f);
                            e.target.value = '';
                          }}
                        />
                        <span style={{
                          padding: '5px 14px',
                          backgroundColor: isLoading ? '#e2e8f0' : '#eff6ff',
                          color: isLoading ? '#94a3b8' : '#2563eb',
                          border: '1px solid #bfdbfe',
                          borderRadius: '6px',
                          fontSize: '13px',
                          fontWeight: 500,
                        }}>
                          {isLoading ? 'Загрузка...' : 'Загрузить .xlsx'}
                        </span>
                      </label>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* Attach to project */}
        {task && (
          <div style={{ backgroundColor: '#fff', border: '1px solid #e2e8f0', borderRadius: '12px', padding: '16px 20px', marginBottom: '16px' }}>
            {taskProjectId ? (
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <span style={{ fontSize: '14px', color: '#64748b' }}>
                  Проект: <strong style={{ color: '#1e293b' }}>{projects.find((p) => p.id === taskProjectId)?.name ?? taskProjectId}</strong>
                </span>
                <button
                  onClick={async () => { await linkTaskToProject(taskId!, null); setTaskProjectId(null); }}
                  style={{ padding: '4px 12px', backgroundColor: 'transparent', border: '1px solid #e2e8f0', borderRadius: '6px', cursor: 'pointer', fontSize: '13px', color: '#64748b' }}
                >
                  Открепить
                </button>
              </div>
            ) : attachingProject ? (
              <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                <select
                  value={selectedAttachProjectId}
                  onChange={(e) => setSelectedAttachProjectId(e.target.value)}
                  style={{ flex: 1, padding: '8px 12px', border: '1px solid #e2e8f0', borderRadius: '8px', fontSize: '14px' }}
                >
                  <option value="">— Выберите проект —</option>
                  {projects.map((p) => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                </select>
                <button
                  onClick={handleAttachProject}
                  disabled={!selectedAttachProjectId}
                  style={{ padding: '8px 16px', backgroundColor: '#2563eb', color: '#fff', border: 'none', borderRadius: '8px', cursor: selectedAttachProjectId ? 'pointer' : 'not-allowed', fontSize: '14px', fontWeight: 600 }}
                >
                  Прикрепить
                </button>
                <button
                  onClick={() => setAttachingProject(false)}
                  style={{ padding: '8px 14px', backgroundColor: 'transparent', border: '1px solid #e2e8f0', borderRadius: '8px', cursor: 'pointer', fontSize: '14px', color: '#64748b' }}
                >
                  Отмена
                </button>
              </div>
            ) : (
              <button
                onClick={() => setAttachingProject(true)}
                style={{ padding: '6px 16px', backgroundColor: 'transparent', border: '1px solid #e2e8f0', borderRadius: '8px', cursor: 'pointer', fontSize: '13px', color: '#2563eb', fontWeight: 500 }}
              >
                + Прикрепить к проекту
              </button>
            )}
          </div>
        )}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/TaskStatus.tsx frontend/src/api/tasks.ts
git commit -m "feat: file slots UI + estimation badge + attach to project in TaskStatus"
```

---

### Task 15: Final integration check + push

- [ ] **Step 1: Run all backend tests**

```bash
cd /Users/admin/Desktop/смета\ аи/smeta-ai/backend
python -m pytest tests/ -v
```

Expected: all tests PASS

- [ ] **Step 2: Build frontend**

```bash
cd /Users/admin/Desktop/смета\ аи/smeta-ai/frontend
npm run build
```

Expected: build succeeds with no TypeScript errors

- [ ] **Step 3: Push to main**

```bash
cd /Users/admin/Desktop/смета\ аи/smeta-ai
git push origin main
```

Expected: push succeeds, Render triggers new deploy
