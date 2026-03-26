# История изменений и откат (Итерация 4) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить аудит-лог изменений сметы (task_history) с возможностью отката к любому предыдущему состоянию через двухшаговое подтверждение.

**Architecture:** Новая таблица `task_history` хранит полные байты файла в base64, что позволяет физически восстановить предыдущую версию. История пишется при каждом завершении оптимизации (в `_run_optimization_background` и `_handle_optimize_smeta`). Откат — двухшаговый endpoint: сначала проверка зависимых записей, затем каскадное удаление.

**Tech Stack:** FastAPI + SQLAlchemy async (JSON columns) + Alembic / React + TypeScript

---

## File Structure

**Create:**
- `backend/app/models/history.py` — модель TaskHistory
- `backend/alembic/versions/005_task_history.py` — миграция
- `backend/tests/test_task_history.py` — тесты endpoints истории
- `frontend/src/components/HistoryModal.tsx` — модальное окно истории

**Modify:**
- `backend/app/models/__init__.py` — добавить экспорт TaskHistory
- `backend/tests/conftest.py` — импортировать TaskHistory для создания таблицы
- `backend/app/routers/tasks.py` — импорт TaskHistory + запись истории в `_run_optimization_background` + два новых endpoint-а + `delete` в sqlalchemy imports
- `backend/app/services/task_processor.py` — запись истории в `_handle_optimize_smeta`
- `frontend/src/types/index.ts` — добавить HistoryEntry, RevertResponse
- `frontend/src/api/tasks.ts` — добавить getTaskHistory, revertHistory
- `frontend/src/pages/ProjectDetail.tsx` — кнопка «История» + HistoryModal

---

## Task 1: TaskHistory модель + обновление __init__ и conftest

**Files:**
- Create: `backend/app/models/history.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/tests/conftest.py`

- [ ] **Step 1: Создать файл модели**

```python
# backend/app/models/history.py
import uuid as _uuid
from sqlalchemy import String, DateTime, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from datetime import datetime, timezone
from app.database import Base


class TaskHistory(Base):
    __tablename__ = "task_history"

    id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(_uuid.uuid4()),
    )
    task_id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    operation_type: Mapped[str] = mapped_column(String(20), nullable=False)
    slot: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    previous_value: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    new_value: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
```

- [ ] **Step 2: Обновить `backend/app/models/__init__.py`**

Заменить содержимое файла:

```python
from app.models.user import User
from app.models.task import Task
from app.models.result import TaskResult
from app.models.price import PriceWork, PriceMaterial
from app.models.project import Project
from app.models.history import TaskHistory

__all__ = ["User", "Task", "TaskResult", "PriceWork", "PriceMaterial", "Project", "TaskHistory"]
```

- [ ] **Step 3: Обновить `backend/tests/conftest.py`**

Добавить строку импорта после строки `from app.models.project import Project`:

```python
from app.models.history import TaskHistory  # noqa: F401
```

- [ ] **Step 4: Проверить импорт**

```bash
cd /Users/admin/Desktop/смета\ аи/smeta-ai/backend && python -c "from app.models.history import TaskHistory; print('OK:', TaskHistory.__tablename__)"
```

Ожидаемый вывод: `OK: task_history`

- [ ] **Step 5: Commit**

```bash
cd /Users/admin/Desktop/смета\ аи/smeta-ai
git add backend/app/models/history.py backend/app/models/__init__.py backend/tests/conftest.py
git commit -m "feat: add TaskHistory model and register in metadata"
```

---

## Task 2: Alembic миграция 005

**Files:**
- Create: `backend/alembic/versions/005_task_history.py`

- [ ] **Step 1: Создать файл миграции**

```python
# backend/alembic/versions/005_task_history.py
"""Add task_history table

Revision ID: 005
Revises: 004
Create Date: 2026-03-26 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table in inspector.get_table_names()


def upgrade() -> None:
    if not _table_exists("task_history"):
        op.create_table(
            "task_history",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=False),
                nullable=False,
            ),
            sa.Column(
                "task_id",
                postgresql.UUID(as_uuid=False),
                nullable=False,
            ),
            sa.Column("operation_type", sa.String(20), nullable=False),
            sa.Column("slot", sa.String(20), nullable=False),
            sa.Column(
                "description",
                sa.String(500),
                nullable=False,
                server_default="",
            ),
            sa.Column(
                "previous_value",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column(
                "new_value",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.ForeignKeyConstraint(
                ["task_id"],
                ["tasks.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_task_history_task_id_created_at",
            "task_history",
            ["task_id", "created_at"],
        )


def downgrade() -> None:
    op.drop_index("ix_task_history_task_id_created_at", table_name="task_history")
    op.drop_table("task_history")
```

- [ ] **Step 2: Применить миграцию**

```bash
cd /Users/admin/Desktop/смета\ аи/smeta-ai/backend && alembic upgrade head
```

Ожидаемый вывод: `Running upgrade 004 -> 005, Add task_history table`

- [ ] **Step 3: Проверить текущую версию**

```bash
cd /Users/admin/Desktop/смета\ аи/smeta-ai/backend && alembic current
```

Ожидаемый вывод: `005 (head)`

- [ ] **Step 4: Commit**

```bash
cd /Users/admin/Desktop/смета\ аи/smeta-ai
git add backend/alembic/versions/005_task_history.py
git commit -m "feat: add alembic migration 005 for task_history table"
```

---

## Task 3: Запись истории в `_run_optimization_background`

**Files:**
- Modify: `backend/app/routers/tasks.py`

Нужно изменить функцию `_run_optimization_background` (строки 617–721): добавить импорт `TaskHistory` и `delete`, захват предыдущего состояния до оптимизации, запись history-записи после успешного сохранения.

- [ ] **Step 1: Добавить `delete` в импорт sqlalchemy и `TaskHistory` в импорты модулей**

В начале файла `backend/app/routers/tasks.py` изменить строку:
```python
from sqlalchemy import select
```
на:
```python
from sqlalchemy import select, delete
```

И добавить импорт TaskHistory после строки `from app.models.result import TaskResult`:
```python
from app.models.history import TaskHistory
```

- [ ] **Step 2: Обновить функцию `_run_optimization_background`**

Найти функцию `_run_optimization_background` (начинается примерно на строке 617). Заменить её тело полностью на следующее (сигнатура остаётся прежней):

```python
async def _run_optimization_background(
    task_id: str,
    items: list[dict],
    prompt: str,
    estimate_bytes: bytes,
    session_factory,
):
    """Background task: search analogues and generate optimized xlsx."""
    import base64 as _b64
    import structlog as _structlog
    from app.utils.xlsx_optimizer import generate_optimized_xlsx
    from app.services.price_service import PriceService

    _logger = _structlog.get_logger()

    async with session_factory() as db:
        try:
            task = await db.get(Task, task_id)
            if not task:
                return

            # Capture previous optimized slot before overwriting
            prev_result_q = await db.execute(
                select(TaskResult).where(
                    TaskResult.task_id == task_id,
                    TaskResult.slot == "optimized",
                )
            )
            prev_optimized = prev_result_q.scalar_one_or_none()
            prev_estimation_status = "optimized" if prev_optimized else "estimated"

            price_service = PriceService()
            optimization_results = []
            total = len(items)

            for i, item in enumerate(items):
                name = item["name"]
                item_type = item["type"]
                original_price = item["price_incl_vat"]

                task.progress_message = f"Обработано {i}/{total}: {name[:40]}"
                await db.commit()

                found_price = None
                source = "Не найдено"

                try:
                    if item_type == "work":
                        price_data = await price_service.find_work_price(name)
                    else:
                        price_data = await price_service.find_material_price(name)

                    if price_data and price_data.get("price"):
                        found_price = float(price_data["price"])
                        source = price_data.get("source", "Прайс-лист")
                except Exception as e:
                    _logger.warning("price_search_failed", name=name, error=str(e))

                savings_abs = None
                savings_pct = None
                if found_price is not None and found_price < original_price:
                    savings_abs = round(original_price - found_price, 4)
                    savings_pct = round(savings_abs / original_price * 100, 2)
                elif found_price is not None:
                    found_price = None
                    source = "Не найдено (цена не ниже)"

                optimization_results.append({
                    "row_index": item["row_index"],
                    "name": name,
                    "original_price": original_price,
                    "new_price": found_price,
                    "source": source,
                    "savings_abs": savings_abs,
                    "savings_pct": savings_pct,
                    "has_vat": True,
                })

            optimized_bytes = generate_optimized_xlsx(estimate_bytes, optimization_results)

            existing = await db.execute(
                select(TaskResult).where(
                    TaskResult.task_id == task_id,
                    TaskResult.slot == "optimized",
                )
            )
            existing_result = existing.scalar_one_or_none()
            if existing_result:
                existing_result.file_data = optimized_bytes
                existing_result.file_name = "optimized.xlsx"
            else:
                new_result = TaskResult(
                    task_id=task_id,
                    slot="optimized",
                    file_name="optimized.xlsx",
                    mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    file_data=optimized_bytes,
                )
                db.add(new_result)

            # Write history entry
            found_count = sum(1 for r in optimization_results if r["new_price"] is not None)
            previous_value: dict = {}
            if prev_optimized:
                previous_value = {
                    "file_name": prev_optimized.file_name,
                    "file_data_b64": _b64.b64encode(prev_optimized.file_data).decode(),
                    "estimation_status": prev_estimation_status,
                }
            else:
                previous_value = {"estimation_status": prev_estimation_status}

            new_value = {
                "file_name": "optimized.xlsx",
                "file_data_b64": _b64.b64encode(optimized_bytes).decode(),
                "estimation_status": "optimized",
            }

            history = TaskHistory(
                id=str(uuid.uuid4()),
                task_id=task_id,
                operation_type="optimization",
                slot="optimized",
                description=f"Оптимизация: найдено {found_count} из {total} аналогов",
                previous_value=previous_value,
                new_value=new_value,
            )
            db.add(history)

            task.status = "completed"
            task.estimation_status = "optimized"
            task.progress_message = None
            await db.commit()
            _logger.info("optimization_complete", task_id=task_id)

        except Exception as e:
            _logger.error("optimization_failed", task_id=task_id, error=str(e))
            try:
                task = await db.get(Task, task_id)
                if task:
                    task.status = "failed"
                    task.error_message = str(e)
                    await db.commit()
            except Exception:
                pass
```

- [ ] **Step 3: Запустить существующие тесты оптимизации**

```bash
cd /Users/admin/Desktop/смета\ аи/smeta-ai/backend && python -m pytest tests/test_optimize_endpoint.py -v
```

Ожидаемый вывод: все 4 теста PASSED.

- [ ] **Step 4: Commit**

```bash
cd /Users/admin/Desktop/смета\ аи/smeta-ai
git add backend/app/routers/tasks.py
git commit -m "feat: write TaskHistory entry after optimization in _run_optimization_background"
```

---

## Task 4: Запись истории в `_handle_optimize_smeta`

**Files:**
- Modify: `backend/app/services/task_processor.py`

- [ ] **Step 1: Обновить `_handle_optimize_smeta`**

Найти метод `_handle_optimize_smeta` (около строки 1602). Заменить его полностью:

```python
async def _handle_optimize_smeta(self, task: Task) -> None:
    """Handle OPTIMIZE_SMETA: parse uploaded xlsx, find analogues, save optimized xlsx."""
    import base64 as _base64
    import uuid as _uuid
    from app.utils.xlsx_optimizer import parse_estimate_xlsx, get_top_items, generate_optimized_xlsx
    from app.models.history import TaskHistory
    from sqlalchemy import select

    if not task.input_file_data:
        raise ValueError("Нет загруженного файла сметы")

    file_entry = task.input_file_data[0]
    file_bytes = _base64.b64decode(file_entry["content_b64"])

    await self.update_progress("Разбираю файл сметы...")
    items = parse_estimate_xlsx(file_bytes)
    top_items = get_top_items(items, categories=["work", "material"], threshold=0.7)

    # Capture previous optimized slot before overwriting
    prev_result_q = await self.db.execute(
        select(TaskResult).where(
            TaskResult.task_id == self.task_id,
            TaskResult.slot == "optimized",
        )
    )
    prev_optimized = prev_result_q.scalar_one_or_none()
    prev_estimation_status = "optimized" if prev_optimized else "estimated"

    await price_service.load_cache(self.db)
    optimization_results = []
    total = len(top_items)

    for i, item in enumerate(top_items):
        name = item["name"]
        item_type = item["type"]
        original_price = item["price_incl_vat"]
        await self.update_progress(f"Поиск аналогов {i + 1}/{total}: {name[:40]}")

        found_price = None
        source = "Не найдено"
        try:
            if item_type == "work":
                price_data = await price_service.find_work_price(name)
            else:
                price_data = await price_service.find_material_price(name)
            if price_data and price_data.get("price"):
                found_price = float(price_data["price"])
                source = price_data.get("source", "Прайс-лист")
        except Exception:
            pass

        savings_abs = None
        savings_pct = None
        if found_price is not None and found_price < original_price:
            savings_abs = round(original_price - found_price, 4)
            savings_pct = round(savings_abs / original_price * 100, 2)
        elif found_price is not None:
            found_price = None
            source = "Не найдено (цена не ниже)"

        optimization_results.append({
            "row_index": item["row_index"],
            "name": name,
            "original_price": original_price,
            "new_price": found_price,
            "source": source,
            "savings_abs": savings_abs,
            "savings_pct": savings_pct,
            "has_vat": True,
        })

    await self.update_progress("Генерирую оптимизированный файл...")
    optimized_bytes = generate_optimized_xlsx(file_bytes, optimization_results)

    result_record = TaskResult(
        task_id=self.task_id,
        slot="optimized",
        file_name="optimized.xlsx",
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        file_data=optimized_bytes,
    )
    self.db.add(result_record)
    await self.db.commit()

    # Write history entry
    found_count = sum(1 for r in optimization_results if r["new_price"] is not None)
    previous_value: dict = {}
    if prev_optimized:
        previous_value = {
            "file_name": prev_optimized.file_name,
            "file_data_b64": _base64.b64encode(prev_optimized.file_data).decode(),
            "estimation_status": prev_estimation_status,
        }
    else:
        previous_value = {"estimation_status": prev_estimation_status}

    new_value = {
        "file_name": "optimized.xlsx",
        "file_data_b64": _base64.b64encode(optimized_bytes).decode(),
        "estimation_status": "optimized",
    }

    history = TaskHistory(
        id=str(_uuid.uuid4()),
        task_id=self.task_id,
        operation_type="optimization",
        slot="optimized",
        description=f"Оптимизация: найдено {found_count} из {total} аналогов",
        previous_value=previous_value,
        new_value=new_value,
    )
    self.db.add(history)

    # Override the default update_status call in process() with optimized status
    task.estimation_status = "optimized"
    await self.db.commit()
```

Note: `TaskResult` is already used in `task_processor.py` so it's already imported at the top of the file. Verify that `from app.models.result import TaskResult` exists in the file imports.

- [ ] **Step 2: Запустить тесты**

```bash
cd /Users/admin/Desktop/смета\ аи/smeta-ai/backend && python -m pytest tests/ -v -k "not test_history"
```

Ожидаемый вывод: все существующие тесты PASSED.

- [ ] **Step 3: Commit**

```bash
cd /Users/admin/Desktop/смета\ аи/smeta-ai
git add backend/app/services/task_processor.py
git commit -m "feat: write TaskHistory entry in _handle_optimize_smeta"
```

---

## Task 5: GET /tasks/{id}/history endpoint

**Files:**
- Modify: `backend/app/routers/tasks.py`

- [ ] **Step 1: Написать тест**

Создать файл `backend/tests/test_task_history.py`:

```python
"""Tests for GET /tasks/{task_id}/history and POST /tasks/{task_id}/history/{id}/revert."""
import io
import pytest
import pytest_asyncio
import openpyxl
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.models.task import Task
from app.models.result import TaskResult
from app.models.history import TaskHistory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_xlsx_bytes() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Смета"
    headers = [
        "№", "Тип", "Наименование", "Ед. изм.", "Кол-во",
        "Цена работы (за ед.)", "Цена материала (за ед.)",
        "Стоимость работ", "Стоимость материалов",
        "Итого без НДС", "НДС (20%)", "Итого с НДС",
        "Наименование в прайсе", "Источники", "Примечание",
    ]
    for col, h in enumerate(headers, start=1):
        ws.cell(row=1, column=col, value=h)
    ws.cell(row=2, column=2, value="Материал")
    ws.cell(row=2, column=3, value="Кирпич М150")
    ws.cell(row=2, column=4, value="шт")
    ws.cell(row=2, column=5, value=1000)
    ws.cell(row=2, column=7, value=10.0)
    ws.cell(row=2, column=10, value=10000.0)
    ws.cell(row=2, column=11, value=2000.0)
    ws.cell(row=2, column=12, value=12000.0)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


TASK_ID = "d1000000-0000-0000-0000-000000000001"
_TASK_ID_HEX = TASK_ID.replace("-", "")

ENTRY_ID_1 = "e1000000-0000-0000-0000-000000000001"
ENTRY_ID_2 = "e2000000-0000-0000-0000-000000000002"

_ENTRY_ID_1_HEX = ENTRY_ID_1.replace("-", "")
_ENTRY_ID_2_HEX = ENTRY_ID_2.replace("-", "")

_NOW = datetime(2026, 3, 26, 10, 0, 0, tzinfo=timezone.utc)
_LATER = _NOW + timedelta(hours=1)


@pytest_asyncio.fixture
async def seed_history_task(db_session: AsyncSession):
    """Seed a task with one history entry."""
    task = Task(
        id=TASK_ID,
        user_role="user",
        task_type="SMETA_FROM_LIST",
        status="completed",
        estimation_status="optimized",
        input_files=[],
        input_file_data=[],
        chat_history=[],
    )
    db_session.add(task)
    await db_session.flush()

    entry = TaskHistory(
        id=ENTRY_ID_1,
        task_id=TASK_ID,
        operation_type="optimization",
        slot="optimized",
        description="Оптимизация: найдено 1 из 1 аналогов",
        previous_value={"estimation_status": "estimated"},
        new_value={
            "file_name": "optimized.xlsx",
            "file_data_b64": "dGVzdA==",
            "estimation_status": "optimized",
        },
        created_at=_NOW,
    )
    db_session.add(entry)
    await db_session.commit()
    yield
    await db_session.execute(
        text("DELETE FROM task_history WHERE task_id = :tid"), {"tid": _TASK_ID_HEX}
    )
    await db_session.execute(
        text("DELETE FROM tasks WHERE id = :tid"), {"tid": _TASK_ID_HEX}
    )
    await db_session.commit()


# ---------------------------------------------------------------------------
# Tests: GET /history
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_history_returns_entries(
    async_client: AsyncClient, user_token: str, seed_history_task
):
    """GET /history returns 200 with list of entries."""
    resp = await async_client.get(
        f"/tasks/{TASK_ID}/history",
        headers={"Authorization": user_token},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["operation_type"] == "optimization"
    assert data[0]["description"] == "Оптимизация: найдено 1 из 1 аналогов"
    assert "id" in data[0]
    assert "created_at" in data[0]
    # file_data_b64 must NOT be in the response
    assert "file_data_b64" not in data[0]
    assert "previous_value" not in data[0]


@pytest.mark.asyncio
async def test_get_history_task_not_found(async_client: AsyncClient, user_token: str):
    """GET /history returns 404 for nonexistent task."""
    resp = await async_client.get(
        "/tasks/nonexistent-id/history",
        headers={"Authorization": user_token},
    )
    assert resp.status_code == 404
```

- [ ] **Step 2: Запустить тест — убедиться что падает**

```bash
cd /Users/admin/Desktop/смета\ аи/smeta-ai/backend && python -m pytest tests/test_task_history.py::test_get_history_returns_entries -v
```

Ожидаемый вывод: FAIL с `404` или `AttributeError` (endpoint не существует).

- [ ] **Step 3: Добавить Pydantic-модели и endpoint в `tasks.py`**

Найти конец файла `backend/app/routers/tasks.py` (после `optimize_run` endpoint) и добавить:

```python
# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

class HistoryEntryOut(BaseModel):
    id: str
    operation_type: str
    slot: str
    description: str
    created_at: str


@router.get("/{task_id}/history")
async def get_task_history(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Return list of history entries for a task (without file_data_b64)."""
    task = await db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Задача не найдена")

    result = await db.execute(
        select(TaskHistory)
        .where(TaskHistory.task_id == task_id)
        .order_by(TaskHistory.created_at.desc())
    )
    entries = result.scalars().all()
    return [
        HistoryEntryOut(
            id=e.id,
            operation_type=e.operation_type,
            slot=e.slot,
            description=e.description,
            created_at=e.created_at.isoformat(),
        )
        for e in entries
    ]
```

- [ ] **Step 4: Запустить тесты GET history**

```bash
cd /Users/admin/Desktop/смета\ аи/smeta-ai/backend && python -m pytest tests/test_task_history.py::test_get_history_returns_entries tests/test_task_history.py::test_get_history_task_not_found -v
```

Ожидаемый вывод: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
cd /Users/admin/Desktop/смета\ аи/smeta-ai
git add backend/app/routers/tasks.py backend/tests/test_task_history.py
git commit -m "feat: add GET /tasks/{id}/history endpoint"
```

---

## Task 6: POST /tasks/{id}/history/{entry_id}/revert endpoint

**Files:**
- Modify: `backend/app/routers/tasks.py`
- Modify: `backend/tests/test_task_history.py`

- [ ] **Step 1: Написать тесты revert**

Добавить в конец `backend/tests/test_task_history.py`:

```python
# ---------------------------------------------------------------------------
# Fixtures for revert tests
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def seed_two_history_entries(db_session: AsyncSession):
    """Seed a task with two sequential history entries (for cascade test)."""
    task = Task(
        id=TASK_ID,
        user_role="user",
        task_type="SMETA_FROM_LIST",
        status="completed",
        estimation_status="optimized",
        input_files=[],
        input_file_data=[],
        chat_history=[],
    )
    db_session.add(task)
    await db_session.flush()

    entry1 = TaskHistory(
        id=ENTRY_ID_1,
        task_id=TASK_ID,
        operation_type="optimization",
        slot="optimized",
        description="Оптимизация первая",
        previous_value={"estimation_status": "estimated"},
        new_value={"file_name": "opt1.xlsx", "file_data_b64": "dGVzdA==", "estimation_status": "optimized"},
        created_at=_NOW,
    )
    entry2 = TaskHistory(
        id=ENTRY_ID_2,
        task_id=TASK_ID,
        operation_type="optimization",
        slot="optimized",
        description="Оптимизация вторая",
        previous_value={"file_name": "opt1.xlsx", "file_data_b64": "dGVzdA==", "estimation_status": "optimized"},
        new_value={"file_name": "opt2.xlsx", "file_data_b64": "dGVzdDI=", "estimation_status": "optimized"},
        created_at=_LATER,
    )
    db_session.add(entry1)
    db_session.add(entry2)
    await db_session.commit()
    yield
    await db_session.execute(
        text("DELETE FROM task_history WHERE task_id = :tid"), {"tid": _TASK_ID_HEX}
    )
    await db_session.execute(
        text("DELETE FROM tasks WHERE id = :tid"), {"tid": _TASK_ID_HEX}
    )
    await db_session.commit()


# ---------------------------------------------------------------------------
# Tests: POST /history/{entry_id}/revert
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_revert_no_dependents_executes_immediately(
    async_client: AsyncClient, user_token: str, seed_history_task
):
    """Revert with confirm=False and no dependents executes immediately."""
    resp = await async_client.post(
        f"/tasks/{TASK_ID}/history/{ENTRY_ID_1}/revert",
        json={"confirm": False},
        headers={"Authorization": user_token},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("reverted") is True


@pytest.mark.asyncio
async def test_revert_with_dependents_returns_warning(
    async_client: AsyncClient, user_token: str, seed_two_history_entries
):
    """Revert entry1 with confirm=False returns warning when entry2 exists."""
    resp = await async_client.post(
        f"/tasks/{TASK_ID}/history/{ENTRY_ID_1}/revert",
        json={"confirm": False},
        headers={"Authorization": user_token},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("warning") is True
    assert isinstance(data.get("dependent_entries"), list)
    assert len(data["dependent_entries"]) == 1
    assert data["dependent_entries"][0]["id"] == ENTRY_ID_2


@pytest.mark.asyncio
async def test_revert_confirm_true_cascades(
    async_client: AsyncClient, user_token: str, seed_two_history_entries
):
    """confirm=True executes cascade rollback and returns reverted=True."""
    resp = await async_client.post(
        f"/tasks/{TASK_ID}/history/{ENTRY_ID_1}/revert",
        json={"confirm": True},
        headers={"Authorization": user_token},
    )
    assert resp.status_code == 200
    assert resp.json().get("reverted") is True

    # Verify via GET /history: original entries are gone, a revert entry exists
    hist_resp = await async_client.get(
        f"/tasks/{TASK_ID}/history",
        headers={"Authorization": user_token},
    )
    assert hist_resp.status_code == 200
    history = hist_resp.json()
    ids = [e["id"] for e in history]
    assert ENTRY_ID_1 not in ids
    assert ENTRY_ID_2 not in ids
    assert any(e["operation_type"] == "revert" for e in history)


@pytest.mark.asyncio
async def test_revert_entry_not_found(async_client: AsyncClient, user_token: str, seed_history_task):
    """Revert returns 404 for nonexistent history entry."""
    resp = await async_client.post(
        f"/tasks/{TASK_ID}/history/nonexistent-entry-id/revert",
        json={"confirm": False},
        headers={"Authorization": user_token},
    )
    assert resp.status_code == 404
```

- [ ] **Step 2: Запустить revert тесты — убедиться что падают**

```bash
cd /Users/admin/Desktop/смета\ аи/smeta-ai/backend && python -m pytest tests/test_task_history.py -v -k "revert"
```

Ожидаемый вывод: все revert-тесты FAIL (404 — endpoint не существует).

- [ ] **Step 3: Добавить revert endpoint в `tasks.py`**

В конец файла `backend/app/routers/tasks.py` добавить (после `get_task_history`):

```python
class RevertBody(BaseModel):
    confirm: bool = False


@router.post("/{task_id}/history/{entry_id}/revert")
async def revert_history(
    task_id: str,
    entry_id: str,
    body: RevertBody,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Revert task to state before a given history entry.

    confirm=False: if there are later dependent entries, returns a warning list.
                   If no dependents, executes rollback immediately.
    confirm=True:  executes cascade rollback unconditionally.
    """
    import base64 as _b64

    task = await db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Задача не найдена")

    entry_result = await db.execute(
        select(TaskHistory).where(
            TaskHistory.task_id == task_id,
            TaskHistory.id == entry_id,
        )
    )
    entry = entry_result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Запись истории не найдена")

    # Find dependent entries (created after this entry)
    dep_result = await db.execute(
        select(TaskHistory)
        .where(
            TaskHistory.task_id == task_id,
            TaskHistory.created_at > entry.created_at,
        )
        .order_by(TaskHistory.created_at.asc())
    )
    dependent = dep_result.scalars().all()

    if not body.confirm and dependent:
        return {
            "warning": True,
            "dependent_entries": [
                {
                    "id": d.id,
                    "description": d.description,
                    "created_at": d.created_at.isoformat(),
                }
                for d in dependent
            ],
        }

    # Execute rollback
    prev = entry.previous_value or {}

    # Delete current TaskResult for this slot and optionally restore previous
    cur_result = await db.execute(
        select(TaskResult).where(
            TaskResult.task_id == task_id,
            TaskResult.slot == entry.slot,
        )
    )
    current_file = cur_result.scalar_one_or_none()
    if current_file:
        await db.delete(current_file)
        await db.flush()

    if prev.get("file_data_b64"):
        restored_bytes = _b64.b64decode(prev["file_data_b64"])
        restored = TaskResult(
            task_id=task_id,
            slot=entry.slot,
            file_name=prev.get("file_name", "restored.xlsx"),
            mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            file_data=restored_bytes,
        )
        db.add(restored)

    # Restore task estimation_status
    task.estimation_status = prev.get("estimation_status", "estimated")

    # Delete this entry and all later entries for this task
    await db.execute(
        delete(TaskHistory).where(
            TaskHistory.task_id == task_id,
            TaskHistory.created_at >= entry.created_at,
        )
    )

    # Write revert entry
    revert_entry = TaskHistory(
        id=str(uuid.uuid4()),
        task_id=task_id,
        operation_type="revert",
        slot=entry.slot,
        description=f"Откат к состоянию до: {entry.description}",
        previous_value=entry.new_value,
        new_value=prev,
    )
    db.add(revert_entry)
    await db.commit()

    return {"reverted": True}
```

- [ ] **Step 4: Запустить все тесты истории**

```bash
cd /Users/admin/Desktop/смета\ аи/smeta-ai/backend && python -m pytest tests/test_task_history.py -v
```

Ожидаемый вывод: все 7 тестов PASSED.

- [ ] **Step 5: Запустить полный suite**

```bash
cd /Users/admin/Desktop/смета\ аи/smeta-ai/backend && python -m pytest tests/ -v
```

Ожидаемый вывод: все тесты PASSED.

- [ ] **Step 6: Commit**

```bash
cd /Users/admin/Desktop/смета\ аи/smeta-ai
git add backend/app/routers/tasks.py backend/tests/test_task_history.py
git commit -m "feat: add POST /tasks/{id}/history/{entry_id}/revert endpoint with cascade support"
```

---

## Task 7: Frontend типы и API функции

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/api/tasks.ts`

- [ ] **Step 1: Добавить типы в `frontend/src/types/index.ts`**

В конец файла добавить:

```typescript
export interface HistoryEntry {
  id: string;
  operation_type: 'optimization' | 'analog' | 'manual_edit' | 'revert';
  slot: string;
  description: string;
  created_at: string;
}

export interface RevertResponse {
  reverted?: boolean;
  warning?: boolean;
  dependent_entries?: Array<{
    id: string;
    description: string;
    created_at: string;
  }>;
}
```

- [ ] **Step 2: Добавить API функции в `frontend/src/api/tasks.ts`**

Сначала обновить существующий импорт в начале файла — добавить `HistoryEntry` и `RevertResponse`:

```typescript
// Найти строку:
import { Task, TaskResult } from '../types';
// Заменить на:
import { Task, TaskResult, HistoryEntry, RevertResponse } from '../types';
```

Затем в конец файла добавить:

```typescript
// ---------------------------------------------------------------------------
// History
// ---------------------------------------------------------------------------

export async function getTaskHistory(taskId: string): Promise<HistoryEntry[]> {
  const res = await apiClient.get<HistoryEntry[]>(`/tasks/${taskId}/history`);
  return res.data;
}

export async function revertHistory(
  taskId: string,
  entryId: string,
  confirm: boolean,
): Promise<RevertResponse> {
  const res = await apiClient.post<RevertResponse>(
    `/tasks/${taskId}/history/${entryId}/revert`,
    { confirm },
  );
  return res.data;
}
```

- [ ] **Step 3: Проверить что TypeScript компилируется без ошибок**

```bash
cd /Users/admin/Desktop/смета\ аи/smeta-ai/frontend && npx tsc --noEmit
```

Ожидаемый вывод: без ошибок (exit code 0).

- [ ] **Step 4: Commit**

```bash
cd /Users/admin/Desktop/смета\ аи/smeta-ai
git add frontend/src/types/index.ts frontend/src/api/tasks.ts
git commit -m "feat: add HistoryEntry/RevertResponse types and history API functions"
```

---

## Task 8: HistoryModal компонент

**Files:**
- Create: `frontend/src/components/HistoryModal.tsx`

- [ ] **Step 1: Создать компонент**

```tsx
// frontend/src/components/HistoryModal.tsx
import React, { useState, useEffect } from 'react';
import { getTaskHistory, revertHistory } from '../api/tasks';
import { HistoryEntry } from '../types';

interface HistoryModalProps {
  taskId: string;
  onClose: () => void;
}

const OPERATION_ICONS: Record<string, string> = {
  optimization: '🔧',
  analog: '🔄',
  manual_edit: '✏️',
  revert: '⏮',
};

const OPERATION_LABELS: Record<string, string> = {
  optimization: 'Оптимизация',
  analog: 'Аналог',
  manual_edit: 'Редактирование',
  revert: 'Откат',
};

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString('ru-RU', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

const HistoryModal: React.FC<HistoryModalProps> = ({ taskId, onClose }) => {
  const [loading, setLoading] = useState(true);
  const [entries, setEntries] = useState<HistoryEntry[]>([]);
  const [fetchError, setFetchError] = useState('');
  const [revertingId, setRevertingId] = useState<string | null>(null);
  const [dependentEntries, setDependentEntries] = useState<
    Array<{ id: string; description: string; created_at: string }>
  >([]);
  const [actionPending, setActionPending] = useState(false);
  const [actionError, setActionError] = useState('');

  useEffect(() => {
    loadHistory();
  }, [taskId]);

  async function loadHistory() {
    setLoading(true);
    setFetchError('');
    try {
      const data = await getTaskHistory(taskId);
      setEntries(data);
    } catch {
      setFetchError('Не удалось загрузить историю изменений');
    } finally {
      setLoading(false);
    }
  }

  async function handleRevertClick(entryId: string) {
    setActionPending(true);
    setActionError('');
    try {
      const result = await revertHistory(taskId, entryId, false);
      if (result.reverted) {
        onClose();
      } else if (result.warning) {
        setRevertingId(entryId);
        setDependentEntries(result.dependent_entries || []);
      }
    } catch {
      setActionError('Ошибка при попытке отката');
    } finally {
      setActionPending(false);
    }
  }

  async function handleConfirmRevert() {
    if (!revertingId) return;
    setActionPending(true);
    setActionError('');
    try {
      await revertHistory(taskId, revertingId, true);
      onClose();
    } catch {
      setActionError('Ошибка при выполнении отката');
    } finally {
      setActionPending(false);
    }
  }

  function cancelRevert() {
    setRevertingId(null);
    setDependentEntries([]);
    setActionError('');
  }

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'rgba(0,0,0,0.5)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        style={{
          background: '#fff',
          borderRadius: '12px',
          padding: '24px',
          width: '560px',
          maxWidth: '95vw',
          maxHeight: '80vh',
          overflowY: 'auto',
          boxShadow: '0 20px 60px rgba(0,0,0,0.2)',
        }}
      >
        {/* Header */}
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: '20px',
          }}
        >
          <h3 style={{ margin: 0, fontSize: '18px', fontWeight: 700, color: '#1e293b' }}>
            История изменений
          </h3>
          <button
            onClick={onClose}
            style={{
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              fontSize: '22px',
              color: '#94a3b8',
              lineHeight: 1,
            }}
          >
            ×
          </button>
        </div>

        {/* Warning panel */}
        {revertingId && (
          <div
            style={{
              background: '#fef3c7',
              border: '1px solid #fcd34d',
              borderRadius: '8px',
              padding: '16px',
              marginBottom: '16px',
            }}
          >
            <p style={{ margin: '0 0 10px', fontWeight: 600, color: '#92400e' }}>
              Следующие изменения будут удалены:
            </p>
            <ul style={{ margin: '0 0 14px', paddingLeft: '20px' }}>
              {dependentEntries.map((d) => (
                <li key={d.id} style={{ fontSize: '13px', marginBottom: '4px', color: '#78350f' }}>
                  {d.description}{' '}
                  <span style={{ color: '#a16207' }}>({formatDate(d.created_at)})</span>
                </li>
              ))}
            </ul>
            <div style={{ display: 'flex', gap: '8px' }}>
              <button
                onClick={cancelRevert}
                style={{
                  padding: '7px 16px',
                  background: '#f1f5f9',
                  border: '1px solid #e2e8f0',
                  borderRadius: '8px',
                  cursor: 'pointer',
                  fontSize: '13px',
                }}
              >
                Отмена
              </button>
              <button
                onClick={handleConfirmRevert}
                disabled={actionPending}
                style={{
                  padding: '7px 16px',
                  background: '#dc2626',
                  color: '#fff',
                  border: 'none',
                  borderRadius: '8px',
                  cursor: actionPending ? 'not-allowed' : 'pointer',
                  fontSize: '13px',
                  fontWeight: 600,
                  opacity: actionPending ? 0.7 : 1,
                }}
              >
                {actionPending ? 'Откатываем...' : 'Подтвердить откат'}
              </button>
            </div>
          </div>
        )}

        {/* Error */}
        {(fetchError || actionError) && (
          <p style={{ color: '#dc2626', fontSize: '14px', marginBottom: '12px' }}>
            {fetchError || actionError}
          </p>
        )}

        {/* Loading */}
        {loading && (
          <p style={{ color: '#94a3b8', textAlign: 'center', padding: '20px 0' }}>
            Загрузка...
          </p>
        )}

        {/* Empty state */}
        {!loading && entries.length === 0 && !fetchError && (
          <p style={{ color: '#94a3b8', textAlign: 'center', padding: '20px 0' }}>
            Нет истории изменений
          </p>
        )}

        {/* Entry list */}
        {!loading &&
          entries.map((entry) => (
            <div
              key={entry.id}
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'flex-start',
                padding: '12px 0',
                borderBottom: '1px solid #f1f5f9',
              }}
            >
              <div style={{ flex: 1, marginRight: '12px' }}>
                <div style={{ fontSize: '14px', fontWeight: 600, color: '#1e293b' }}>
                  {OPERATION_ICONS[entry.operation_type] ?? '•'}{' '}
                  {OPERATION_LABELS[entry.operation_type] ?? entry.operation_type}
                </div>
                <div style={{ fontSize: '13px', color: '#475569', marginTop: '2px' }}>
                  {entry.description}
                </div>
                <div style={{ fontSize: '12px', color: '#94a3b8', marginTop: '2px' }}>
                  {formatDate(entry.created_at)}
                </div>
              </div>
              {entry.operation_type !== 'revert' && !revertingId && (
                <button
                  onClick={() => handleRevertClick(entry.id)}
                  disabled={actionPending}
                  style={{
                    padding: '5px 12px',
                    background: '#fef2f2',
                    color: '#dc2626',
                    border: '1px solid #fecaca',
                    borderRadius: '8px',
                    cursor: actionPending ? 'not-allowed' : 'pointer',
                    fontSize: '12px',
                    fontWeight: 600,
                    whiteSpace: 'nowrap',
                    opacity: actionPending ? 0.6 : 1,
                  }}
                >
                  Откатить
                </button>
              )}
            </div>
          ))}
      </div>
    </div>
  );
};

export default HistoryModal;
```

- [ ] **Step 2: Проверить TypeScript**

```bash
cd /Users/admin/Desktop/смета\ аи/smeta-ai/frontend && npx tsc --noEmit
```

Ожидаемый вывод: без ошибок.

- [ ] **Step 3: Commit**

```bash
cd /Users/admin/Desktop/смета\ аи/smeta-ai
git add frontend/src/components/HistoryModal.tsx
git commit -m "feat: add HistoryModal component with revert confirmation"
```

---

## Task 9: Интеграция в ProjectDetail

**Files:**
- Modify: `frontend/src/pages/ProjectDetail.tsx`

- [ ] **Step 1: Добавить импорт HistoryModal**

В начало файла `frontend/src/pages/ProjectDetail.tsx` после строки:
```typescript
import OptimizeModal from '../components/OptimizeModal';
```
добавить:
```typescript
import HistoryModal from '../components/HistoryModal';
```

- [ ] **Step 2: Добавить state `historyTaskId`**

Найти строку:
```typescript
const [optimizingTaskId, setOptimizingTaskId] = useState<string | null>(null);
```
После неё добавить:
```typescript
const [historyTaskId, setHistoryTaskId] = useState<string | null>(null);
```

- [ ] **Step 3: Добавить кнопку «История» рядом с «Оптимизировать»**

Найти блок:
```tsx
{task.estimation_status === 'estimated' && (
  <button
    onClick={(e) => {
      e.stopPropagation();
      setOptimizingTaskId(task.id);
    }}
    style={{
      padding: '4px 12px',
      backgroundColor: '#eff6ff',
      color: '#2563eb',
      border: '1px solid #bfdbfe',
      borderRadius: '8px',
      cursor: 'pointer',
      fontSize: '12px',
      fontWeight: 600,
    }}
  >
    Оптимизировать
  </button>
)}
```

Заменить его на:
```tsx
{task.estimation_status === 'estimated' && (
  <button
    onClick={(e) => {
      e.stopPropagation();
      setOptimizingTaskId(task.id);
    }}
    style={{
      padding: '4px 12px',
      backgroundColor: '#eff6ff',
      color: '#2563eb',
      border: '1px solid #bfdbfe',
      borderRadius: '8px',
      cursor: 'pointer',
      fontSize: '12px',
      fontWeight: 600,
    }}
  >
    Оптимизировать
  </button>
)}
{['estimated', 'optimized'].includes(task.estimation_status) && (
  <button
    onClick={(e) => {
      e.stopPropagation();
      setHistoryTaskId(task.id);
    }}
    style={{
      padding: '4px 12px',
      backgroundColor: '#f8fafc',
      color: '#475569',
      border: '1px solid #e2e8f0',
      borderRadius: '8px',
      cursor: 'pointer',
      fontSize: '12px',
      fontWeight: 600,
    }}
  >
    История
  </button>
)}
```

- [ ] **Step 4: Добавить HistoryModal рядом с OptimizeModal**

Найти блок:
```tsx
{optimizingTaskId && (
  <OptimizeModal
    taskId={optimizingTaskId}
    onClose={() => {
      setOptimizingTaskId(null);
      loadProject();
    }}
  />
)}
```

После него добавить:
```tsx
{historyTaskId && (
  <HistoryModal
    taskId={historyTaskId}
    onClose={() => {
      setHistoryTaskId(null);
      loadProject();
    }}
  />
)}
```

- [ ] **Step 5: Проверить TypeScript**

```bash
cd /Users/admin/Desktop/смета\ аи/smeta-ai/frontend && npx tsc --noEmit
```

Ожидаемый вывод: без ошибок.

- [ ] **Step 6: Запустить сборку**

```bash
cd /Users/admin/Desktop/смета\ аи/smeta-ai/frontend && npm run build
```

Ожидаемый вывод: `✓ built in ...ms` без ошибок.

- [ ] **Step 7: Запустить все backend тесты финально**

```bash
cd /Users/admin/Desktop/смета\ аи/smeta-ai/backend && python -m pytest tests/ -v
```

Ожидаемый вывод: все тесты PASSED.

- [ ] **Step 8: Commit**

```bash
cd /Users/admin/Desktop/смета\ аи/smeta-ai
git add frontend/src/pages/ProjectDetail.tsx
git commit -m "feat: add История button and HistoryModal to ProjectDetail"
```
