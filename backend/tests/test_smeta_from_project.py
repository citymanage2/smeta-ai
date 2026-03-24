"""Tests for phased (per-stage) output in SMETA_FROM_PROJECT tasks.

Behaviour under test:
- Stage 1 (research) result is saved as .txt immediately after the stage completes.
- Stage 2 (items list) result is saved as .xlsx immediately after the stage completes.
- Stage 3 (final smeta) result is saved as .xlsx after the stage completes.
- Each stage's output is correctly forwarded to the next stage.
- Progress messages are set for each stage.
"""
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.result import TaskResult
from app.models.task import Task
from app.services.task_processor import TaskProcessor

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

STAGE1_TEXT = "Проверка проекта: всё в порядке. Замечаний нет."

STAGE2_ITEMS = [
    {
        "type": "Работа",
        "name": "Кладка стен",
        "unit": "м3",
        "quantity": 50,
        "section": "КЖ",
        "notes": "",
    },
    {
        "type": "Материал",
        "name": "Кирпич",
        "unit": "шт",
        "quantity": 10000,
        "section": "КЖ",
        "notes": "",
    },
]
STAGE2_CHANGES = "Перечень соответствует проекту."
STAGE2_JSON = json.dumps({"items": STAGE2_ITEMS, "changes_summary": STAGE2_CHANGES})

STAGE3_ITEMS = [
    {
        "type": "Работа",
        "name": "Кладка стен",
        "unit": "м3",
        "quantity": 50,
        "work_price": 1000,
        "material_price": None,
        "notes": "",
    },
    {
        "type": "Материал",
        "name": "Кирпич",
        "unit": "шт",
        "quantity": 10000,
        "work_price": None,
        "material_price": 5,
        "notes": "",
    },
]
STAGE3_JSON = json.dumps({"items": STAGE3_ITEMS})

STAGE2_EXCEL_BYTES = b"<stage2-list-excel>"
STAGE3_EXCEL_BYTES = b"<stage3-smeta-excel>"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def smeta_task(db_session):
    """A SMETA_FROM_PROJECT task with no attached files."""
    task = Task(
        id=str(uuid.uuid4()),
        user_role="user",
        task_type="SMETA_FROM_PROJECT",
        status="processing",
        input_files=[],
        input_file_data=[],
        chat_history=[],
    )
    db_session.add(task)
    await db_session.commit()
    return task


def _mock_price_service():
    svc = MagicMock()
    svc.load_cache = AsyncMock()
    svc._works_cache = []
    svc._materials_cache = []
    return svc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_claude_side_effect(
    stage1=STAGE1_TEXT, stage2=STAGE2_JSON, stage3=STAGE3_JSON
):
    """Return a list used as AsyncMock.side_effect for the three call_claude calls."""
    return [stage1, stage2, stage3]


# ---------------------------------------------------------------------------
# Tests — result count and types
# ---------------------------------------------------------------------------


async def test_three_results_saved_total(db_session, smeta_task):
    """All three stages each produce one saved result — 3 total."""
    processor = TaskProcessor(smeta_task.id, db_session)

    with (
        patch(
            "app.services.task_processor.call_claude", new_callable=AsyncMock
        ) as mock_claude,
        patch(
            "app.services.task_processor.generate_list_project",
            return_value=STAGE2_EXCEL_BYTES,
        ),
        patch(
            "app.services.task_processor.generate_smeta_from_project",
            return_value=STAGE3_EXCEL_BYTES,
        ),
        patch(
            "app.services.task_processor.price_service", _mock_price_service()
        ),
    ):
        mock_claude.side_effect = _make_claude_side_effect()
        await processor._handle_smeta_from_project(smeta_task)

    rows = (
        await db_session.execute(
            select(TaskResult).where(TaskResult.task_id == smeta_task.id)
        )
    ).scalars().all()

    assert len(rows) == 3, f"Expected 3 saved results, got {len(rows)}"


async def test_stage1_result_is_text_file(db_session, smeta_task):
    """Stage 1 saves a plain-text file containing the research result."""
    processor = TaskProcessor(smeta_task.id, db_session)

    with (
        patch(
            "app.services.task_processor.call_claude", new_callable=AsyncMock
        ) as mock_claude,
        patch(
            "app.services.task_processor.generate_list_project",
            return_value=STAGE2_EXCEL_BYTES,
        ),
        patch(
            "app.services.task_processor.generate_smeta_from_project",
            return_value=STAGE3_EXCEL_BYTES,
        ),
        patch(
            "app.services.task_processor.price_service", _mock_price_service()
        ),
    ):
        mock_claude.side_effect = _make_claude_side_effect()
        await processor._handle_smeta_from_project(smeta_task)

    rows = (
        await db_session.execute(
            select(TaskResult).where(TaskResult.task_id == smeta_task.id)
        )
    ).scalars().all()

    txt_rows = [r for r in rows if r.mime_type.startswith("text/plain")]
    assert len(txt_rows) == 1, "Expected exactly one text/plain result for stage 1"
    assert STAGE1_TEXT.encode("utf-8") in txt_rows[0].file_data


async def test_stage2_result_is_excel_with_correct_content(db_session, smeta_task):
    """Stage 2 saves an Excel file produced by generate_list_project with the parsed items."""
    processor = TaskProcessor(smeta_task.id, db_session)

    with (
        patch(
            "app.services.task_processor.call_claude", new_callable=AsyncMock
        ) as mock_claude,
        patch(
            "app.services.task_processor.generate_list_project",
            return_value=STAGE2_EXCEL_BYTES,
        ) as mock_gen_list,
        patch(
            "app.services.task_processor.generate_smeta_from_project",
            return_value=STAGE3_EXCEL_BYTES,
        ),
        patch(
            "app.services.task_processor.price_service", _mock_price_service()
        ),
    ):
        mock_claude.side_effect = _make_claude_side_effect()
        await processor._handle_smeta_from_project(smeta_task)

    rows = (
        await db_session.execute(
            select(TaskResult).where(TaskResult.task_id == smeta_task.id)
        )
    ).scalars().all()

    xlsx_rows = [
        r
        for r in rows
        if "spreadsheetml" in r.mime_type and r.file_data == STAGE2_EXCEL_BYTES
    ]
    assert len(xlsx_rows) == 1, "Expected one stage-2 Excel result"

    # generate_list_project must receive the parsed items and changes_summary
    mock_gen_list.assert_called_once_with(STAGE2_ITEMS, STAGE2_CHANGES)


async def test_stage3_result_is_final_smeta_excel(db_session, smeta_task):
    """Stage 3 saves the final smeta Excel produced by generate_smeta_from_project."""
    processor = TaskProcessor(smeta_task.id, db_session)

    with (
        patch(
            "app.services.task_processor.call_claude", new_callable=AsyncMock
        ) as mock_claude,
        patch(
            "app.services.task_processor.generate_list_project",
            return_value=STAGE2_EXCEL_BYTES,
        ),
        patch(
            "app.services.task_processor.generate_smeta_from_project",
            return_value=STAGE3_EXCEL_BYTES,
        ) as mock_gen_smeta,
        patch(
            "app.services.task_processor.price_service", _mock_price_service()
        ),
    ):
        mock_claude.side_effect = _make_claude_side_effect()
        await processor._handle_smeta_from_project(smeta_task)

    rows = (
        await db_session.execute(
            select(TaskResult).where(TaskResult.task_id == smeta_task.id)
        )
    ).scalars().all()

    smeta_rows = [r for r in rows if r.file_data == STAGE3_EXCEL_BYTES]
    assert len(smeta_rows) == 1, "Expected one stage-3 smeta Excel result"

    mock_gen_smeta.assert_called_once_with(
        STAGE3_ITEMS,
        STAGE2_ITEMS,
        research_result=STAGE1_TEXT,
        changes_summary=STAGE2_CHANGES,
    )


# ---------------------------------------------------------------------------
# Tests — result ordering (stage-1 saved before stage-2, stage-2 before stage-3)
# ---------------------------------------------------------------------------


async def test_results_saved_in_stage_order(db_session, smeta_task):
    """Results are persisted in ascending stage order (stage 1 first, stage 3 last)."""
    processor = TaskProcessor(smeta_task.id, db_session)

    with (
        patch(
            "app.services.task_processor.call_claude", new_callable=AsyncMock
        ) as mock_claude,
        patch(
            "app.services.task_processor.generate_list_project",
            return_value=STAGE2_EXCEL_BYTES,
        ),
        patch(
            "app.services.task_processor.generate_smeta_from_project",
            return_value=STAGE3_EXCEL_BYTES,
        ),
        patch(
            "app.services.task_processor.price_service", _mock_price_service()
        ),
    ):
        mock_claude.side_effect = _make_claude_side_effect()
        await processor._handle_smeta_from_project(smeta_task)

    rows = (
        await db_session.execute(
            select(TaskResult)
            .where(TaskResult.task_id == smeta_task.id)
            .order_by(TaskResult.id)
        )
    ).scalars().all()

    assert len(rows) == 3
    # First saved = text (stage 1)
    assert rows[0].mime_type.startswith("text/plain")
    # Second saved = stage-2 list Excel
    assert rows[1].file_data == STAGE2_EXCEL_BYTES
    # Third saved = stage-3 smeta Excel
    assert rows[2].file_data == STAGE3_EXCEL_BYTES


# ---------------------------------------------------------------------------
# Tests — inter-stage data propagation
# ---------------------------------------------------------------------------


async def test_stage1_output_included_in_stage2_prompt(db_session, smeta_task):
    """The research text from stage 1 appears in the prompt sent to stage 2."""
    processor = TaskProcessor(smeta_task.id, db_session)
    captured = []

    async def capturing_claude(messages, **kwargs):
        captured.append(messages)
        n = len(captured)
        if n == 1:
            return STAGE1_TEXT
        if n == 2:
            return STAGE2_JSON
        return STAGE3_JSON

    with (
        patch("app.services.task_processor.call_claude", side_effect=capturing_claude),
        patch(
            "app.services.task_processor.generate_list_project",
            return_value=STAGE2_EXCEL_BYTES,
        ),
        patch(
            "app.services.task_processor.generate_smeta_from_project",
            return_value=STAGE3_EXCEL_BYTES,
        ),
        patch(
            "app.services.task_processor.price_service", _mock_price_service()
        ),
    ):
        await processor._handle_smeta_from_project(smeta_task)

    assert len(captured) == 3, "Expected exactly 3 call_claude invocations"
    stage2_content = str(captured[1])
    assert STAGE1_TEXT in stage2_content, (
        "Stage-1 research text must be present in the stage-2 prompt"
    )


async def test_stage2_items_included_in_stage3_message(db_session, smeta_task):
    """The items list from stage 2 appears in the message sent to stage 3."""
    processor = TaskProcessor(smeta_task.id, db_session)
    captured = []

    async def capturing_claude(messages, **kwargs):
        captured.append(messages)
        n = len(captured)
        if n == 1:
            return STAGE1_TEXT
        if n == 2:
            return STAGE2_JSON
        return STAGE3_JSON

    with (
        patch("app.services.task_processor.call_claude", side_effect=capturing_claude),
        patch(
            "app.services.task_processor.generate_list_project",
            return_value=STAGE2_EXCEL_BYTES,
        ),
        patch(
            "app.services.task_processor.generate_smeta_from_project",
            return_value=STAGE3_EXCEL_BYTES,
        ),
        patch(
            "app.services.task_processor.price_service", _mock_price_service()
        ),
    ):
        await processor._handle_smeta_from_project(smeta_task)

    assert len(captured) == 3
    stage3_content = str(captured[2])
    # Item names from STAGE2_ITEMS must appear in the stage-3 message
    assert "Кладка стен" in stage3_content, (
        "Stage-2 item names must be present in the stage-3 message"
    )
    assert "Кирпич" in stage3_content


# ---------------------------------------------------------------------------
# Tests — progress messages
# ---------------------------------------------------------------------------


async def test_progress_messages_indicate_all_three_stages(db_session, smeta_task):
    """Progress messages mention each of the three stages."""
    processor = TaskProcessor(smeta_task.id, db_session)
    recorded: list[str] = []

    original = processor.update_progress

    async def tracking(msg: str) -> None:
        recorded.append(msg)
        await original(msg)

    processor.update_progress = tracking  # type: ignore[method-assign]

    with (
        patch(
            "app.services.task_processor.call_claude", new_callable=AsyncMock
        ) as mock_claude,
        patch(
            "app.services.task_processor.generate_list_project",
            return_value=STAGE2_EXCEL_BYTES,
        ),
        patch(
            "app.services.task_processor.generate_smeta_from_project",
            return_value=STAGE3_EXCEL_BYTES,
        ),
        patch(
            "app.services.task_processor.price_service", _mock_price_service()
        ),
    ):
        mock_claude.side_effect = _make_claude_side_effect()
        await processor._handle_smeta_from_project(smeta_task)

    all_text = " ".join(recorded)
    assert "1" in all_text, "No message mentioning stage 1"
    assert "2" in all_text, "No message mentioning stage 2"
    assert "3" in all_text, "No message mentioning stage 3"
