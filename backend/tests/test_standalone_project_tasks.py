"""Tests for standalone single-stage task types extracted from SMETA_FROM_PROJECT:

  RESEARCH_PROJECT  — runs the project-review prompt, saves a .txt result.
  LIST_FROM_PROJECT — runs the items-list prompt, saves an .xlsx result.

Each task type must:
  - Save exactly one result file after completion.
  - Use the correct MIME type for that file.
  - Persist the Claude response in the saved file.
  - Set progress messages during processing.
  - Be handled by the top-level process() dispatcher (i.e. task_type is recognised).
"""
import json
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.result import TaskResult
from app.models.task import Task
from app.services.task_processor import TaskProcessor

# ---------------------------------------------------------------------------
# Shared fixtures & helpers
# ---------------------------------------------------------------------------

RESEARCH_TEXT = "Анализ проекта завершён. Замечаний не выявлено."

LIST_ITEMS = [
    {"type": "Работа", "name": "Монтаж кровли", "unit": "м2", "quantity": 120, "section": "АР", "notes": ""},
    {"type": "Материал", "name": "Профнастил", "unit": "м2", "quantity": 130, "section": "АР", "notes": ""},
]
LIST_CHANGES = "Перечень сформирован по проектной документации."
LIST_JSON = json.dumps({"items": LIST_ITEMS, "changes_summary": LIST_CHANGES})

LIST_EXCEL_BYTES = b"<list-xlsx>"


def _make_task(task_type: str) -> Task:
    return Task(
        id=str(uuid.uuid4()),
        user_role="user",
        task_type=task_type,
        status="processing",
        input_files=[],
        input_file_data=[],
        chat_history=[],
    )


def _mock_price():
    svc = MagicMock()
    svc.load_cache = AsyncMock()
    svc._works_cache = []
    svc._materials_cache = []
    return svc


@pytest_asyncio.fixture
async def research_task(db_session):
    task = _make_task("RESEARCH_PROJECT")
    db_session.add(task)
    await db_session.commit()
    return task


@pytest_asyncio.fixture
async def list_task(db_session):
    task = _make_task("LIST_FROM_PROJECT")
    db_session.add(task)
    await db_session.commit()
    return task


# ---------------------------------------------------------------------------
# RESEARCH_PROJECT tests
# ---------------------------------------------------------------------------


async def test_research_project_saves_one_result(db_session, research_task):
    """RESEARCH_PROJECT saves exactly one result file."""
    processor = TaskProcessor(research_task.id, db_session)

    with patch(
        "app.services.task_processor.call_claude",
        new_callable=AsyncMock,
        return_value=RESEARCH_TEXT,
    ):
        await processor._handle_research_project(research_task)

    rows = (
        await db_session.execute(
            select(TaskResult).where(TaskResult.task_id == research_task.id)
        )
    ).scalars().all()

    assert len(rows) == 1


async def test_research_project_result_is_text_plain(db_session, research_task):
    """RESEARCH_PROJECT result has MIME type text/plain."""
    processor = TaskProcessor(research_task.id, db_session)

    with patch(
        "app.services.task_processor.call_claude",
        new_callable=AsyncMock,
        return_value=RESEARCH_TEXT,
    ):
        await processor._handle_research_project(research_task)

    rows = (
        await db_session.execute(
            select(TaskResult).where(TaskResult.task_id == research_task.id)
        )
    ).scalars().all()

    assert rows[0].mime_type.startswith("text/plain")


async def test_research_project_result_contains_claude_response(db_session, research_task):
    """RESEARCH_PROJECT file data contains the text Claude returned."""
    processor = TaskProcessor(research_task.id, db_session)

    with patch(
        "app.services.task_processor.call_claude",
        new_callable=AsyncMock,
        return_value=RESEARCH_TEXT,
    ):
        await processor._handle_research_project(research_task)

    rows = (
        await db_session.execute(
            select(TaskResult).where(TaskResult.task_id == research_task.id)
        )
    ).scalars().all()

    assert RESEARCH_TEXT.encode("utf-8") in rows[0].file_data


async def test_research_project_progress_messages(db_session, research_task):
    """RESEARCH_PROJECT emits at least one progress message."""
    processor = TaskProcessor(research_task.id, db_session)
    recorded: list[str] = []
    original = processor.update_progress

    async def track(msg: str) -> None:
        recorded.append(msg)
        await original(msg)

    processor.update_progress = track  # type: ignore[method-assign]

    with patch(
        "app.services.task_processor.call_claude",
        new_callable=AsyncMock,
        return_value=RESEARCH_TEXT,
    ):
        await processor._handle_research_project(research_task)

    assert len(recorded) >= 1, "Expected at least one progress message"


async def test_research_project_dispatched_by_process(db_session, research_task):
    """process() recognises RESEARCH_PROJECT and routes to the correct handler."""
    processor = TaskProcessor(research_task.id, db_session)

    handler_called = False
    original_handler = processor._handle_research_project

    async def spy_handler(task):
        nonlocal handler_called
        handler_called = True
        await original_handler(task)

    processor._handle_research_project = spy_handler  # type: ignore[method-assign]

    with patch(
        "app.services.task_processor.call_claude",
        new_callable=AsyncMock,
        return_value=RESEARCH_TEXT,
    ):
        await processor.process()

    assert handler_called, "_handle_research_project was not called by process()"


# ---------------------------------------------------------------------------
# LIST_FROM_PROJECT tests
# ---------------------------------------------------------------------------


async def test_list_from_project_saves_one_result(db_session, list_task):
    """LIST_FROM_PROJECT saves exactly one result file."""
    processor = TaskProcessor(list_task.id, db_session)

    with (
        patch(
            "app.services.task_processor.call_claude",
            new_callable=AsyncMock,
            return_value=LIST_JSON,
        ),
        patch(
            "app.services.task_processor.generate_list_project",
            return_value=LIST_EXCEL_BYTES,
        ),
    ):
        await processor._handle_list_from_project(list_task)

    rows = (
        await db_session.execute(
            select(TaskResult).where(TaskResult.task_id == list_task.id)
        )
    ).scalars().all()

    assert len(rows) == 1


async def test_list_from_project_result_is_xlsx(db_session, list_task):
    """LIST_FROM_PROJECT result is an Excel file."""
    processor = TaskProcessor(list_task.id, db_session)

    with (
        patch(
            "app.services.task_processor.call_claude",
            new_callable=AsyncMock,
            return_value=LIST_JSON,
        ),
        patch(
            "app.services.task_processor.generate_list_project",
            return_value=LIST_EXCEL_BYTES,
        ),
    ):
        await processor._handle_list_from_project(list_task)

    rows = (
        await db_session.execute(
            select(TaskResult).where(TaskResult.task_id == list_task.id)
        )
    ).scalars().all()

    assert "spreadsheetml" in rows[0].mime_type


async def test_list_from_project_result_contains_excel_bytes(db_session, list_task):
    """LIST_FROM_PROJECT result file_data is exactly what generate_list_project returned."""
    processor = TaskProcessor(list_task.id, db_session)

    with (
        patch(
            "app.services.task_processor.call_claude",
            new_callable=AsyncMock,
            return_value=LIST_JSON,
        ),
        patch(
            "app.services.task_processor.generate_list_project",
            return_value=LIST_EXCEL_BYTES,
        ),
    ):
        await processor._handle_list_from_project(list_task)

    rows = (
        await db_session.execute(
            select(TaskResult).where(TaskResult.task_id == list_task.id)
        )
    ).scalars().all()

    assert rows[0].file_data == LIST_EXCEL_BYTES


async def test_list_from_project_calls_generate_list_project_with_items(db_session, list_task):
    """generate_list_project is called with the parsed items and changes_summary."""
    processor = TaskProcessor(list_task.id, db_session)

    with (
        patch(
            "app.services.task_processor.call_claude",
            new_callable=AsyncMock,
            return_value=LIST_JSON,
        ),
        patch(
            "app.services.task_processor.generate_list_project",
            return_value=LIST_EXCEL_BYTES,
        ) as mock_gen,
    ):
        await processor._handle_list_from_project(list_task)

    mock_gen.assert_called_once_with(LIST_ITEMS, LIST_CHANGES)


async def test_list_from_project_progress_messages(db_session, list_task):
    """LIST_FROM_PROJECT emits at least one progress message."""
    processor = TaskProcessor(list_task.id, db_session)
    recorded: list[str] = []
    original = processor.update_progress

    async def track(msg: str) -> None:
        recorded.append(msg)
        await original(msg)

    processor.update_progress = track  # type: ignore[method-assign]

    with (
        patch(
            "app.services.task_processor.call_claude",
            new_callable=AsyncMock,
            return_value=LIST_JSON,
        ),
        patch(
            "app.services.task_processor.generate_list_project",
            return_value=LIST_EXCEL_BYTES,
        ),
    ):
        await processor._handle_list_from_project(list_task)

    assert len(recorded) >= 1, "Expected at least one progress message"


async def test_list_from_project_dispatched_by_process(db_session, list_task):
    """process() recognises LIST_FROM_PROJECT and routes to the correct handler."""
    processor = TaskProcessor(list_task.id, db_session)

    handler_called = False
    original_handler = processor._handle_list_from_project

    async def spy_handler(task):
        nonlocal handler_called
        handler_called = True
        await original_handler(task)

    processor._handle_list_from_project = spy_handler  # type: ignore[method-assign]

    with (
        patch(
            "app.services.task_processor.call_claude",
            new_callable=AsyncMock,
            return_value=LIST_JSON,
        ),
        patch(
            "app.services.task_processor.generate_list_project",
            return_value=LIST_EXCEL_BYTES,
        ),
    ):
        await processor.process()

    assert handler_called, "_handle_list_from_project was not called by process()"
