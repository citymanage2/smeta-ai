"""TDD tests for SMETA_FROM_LIST batching.

Required behaviour:
- Items list is split into batches of SMETA_BATCH_SIZE (10).
- Each batch gets its own Claude API call.
- Results from all batches are combined in order.
- Progress message is updated after each batch (text contains "батч N из M").
- If a batch's Claude call exceeds SMETA_BATCH_TIMEOUT_SECS, that batch is
  skipped (original items kept without pricing) and processing continues.
- The final Excel is saved as a TaskResult.
"""
import asyncio
import base64
import io
import json
import uuid

import openpyxl
import pytest
import pytest_asyncio
from sqlalchemy import select
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.result import TaskResult
from app.models.task import Task
from app.services.task_processor import TaskProcessor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_xlsx_b64(items: list[dict]) -> str:
    """Create an in-memory Excel with standard list headers and return as base64."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Тип", "Наименование", "Ед. изм.", "Кол-во", "Примечание"])
    for item in items:
        ws.append([
            item.get("type", "Работа"),
            item.get("name", ""),
            item.get("unit", "м2"),
            item.get("quantity", 1),
            item.get("notes", ""),
        ])
    buf = io.BytesIO()
    wb.save(buf)
    return base64.b64encode(buf.getvalue()).decode()


def _raw_items(n: int) -> list[dict]:
    """Return n simple items without pricing."""
    return [
        {
            "type": "Работа",
            "name": f"Позиция {i + 1}",
            "unit": "м2",
            "quantity": float(i + 1),
            "notes": "",
        }
        for i in range(n)
    ]


def _priced_response(batch_num: int) -> str:
    """Return a JSON string simulating Claude's response for a single batch."""
    return json.dumps({
        "items": [
            {
                "type": "Работа",
                "name": f"Batch{batch_num}_PricedItem",
                "unit": "м2",
                "quantity": 1,
                "work_price": 100 * batch_num,
                "material_price": None,
                "price_list_name": None,
                "sources": None,
                "notes": "",
            }
        ]
    })


def _mock_price():
    svc = MagicMock()
    svc.load_cache = AsyncMock()
    svc._works_cache = []
    svc._materials_cache = []
    return svc


async def _task_with_excel(db_session, n_items: int) -> Task:
    """Insert a SMETA_FROM_LIST task with an n_items-row Excel into the test DB."""
    xl_b64 = _make_xlsx_b64(_raw_items(n_items))
    task = Task(
        id=str(uuid.uuid4()),
        user_role="user",
        task_type="SMETA_FROM_LIST",
        status="processing",
        input_files=[{
            "name": "list.xlsx",
            "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "size_bytes": 100,
        }],
        input_file_data=[{
            "name": "list.xlsx",
            "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "size_bytes": 100,
            "content_b64": xl_b64,
        }],
        chat_history=[],
    )
    db_session.add(task)
    await db_session.commit()
    return task


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def task_25(db_session):
    return await _task_with_excel(db_session, 25)


@pytest_asyncio.fixture
async def task_20(db_session):
    return await _task_with_excel(db_session, 20)


@pytest_asyncio.fixture
async def task_10(db_session):
    return await _task_with_excel(db_session, 10)


# ---------------------------------------------------------------------------
# _parse_xlsx_items tests
# ---------------------------------------------------------------------------


async def test_parse_xlsx_items_extracts_correct_items(db_session):
    """Items are read from the Excel with correct field mapping."""
    items = [
        {"type": "Работа", "name": "Кладка кирпича", "unit": "м3", "quantity": 15.5, "notes": "основная"},
        {"type": "Материал", "name": "Кирпич М150", "unit": "шт", "quantity": 10000.0, "notes": ""},
    ]
    task = await _task_with_excel(db_session, 0)
    # Replace input_file_data with our specific items
    task.input_file_data = [{
        "name": "list.xlsx",
        "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "size_bytes": 100,
        "content_b64": _make_xlsx_b64(items),
    }]
    await db_session.commit()

    processor = TaskProcessor(task.id, db_session)
    extracted = processor._parse_xlsx_items(task)

    assert len(extracted) == 2
    assert extracted[0]["name"] == "Кладка кирпича"
    assert extracted[0]["unit"] == "м3"
    assert extracted[0]["quantity"] == 15.5
    assert extracted[1]["name"] == "Кирпич М150"
    assert extracted[1]["type"] == "Материал"


async def test_parse_xlsx_items_no_files_returns_empty(db_session):
    """Task with no uploaded files → empty list."""
    task = Task(
        id=str(uuid.uuid4()),
        user_role="user",
        task_type="SMETA_FROM_LIST",
        status="processing",
        input_files=[],
        input_file_data=[],
        chat_history=[],
    )
    db_session.add(task)
    await db_session.commit()

    processor = TaskProcessor(task.id, db_session)
    assert processor._parse_xlsx_items(task) == []


async def test_parse_xlsx_items_non_xlsx_returns_empty(db_session):
    """Task with only PDF → empty list."""
    task = Task(
        id=str(uuid.uuid4()),
        user_role="user",
        task_type="SMETA_FROM_LIST",
        status="processing",
        input_files=[{"name": "doc.pdf", "mime_type": "application/pdf", "size_bytes": 100}],
        input_file_data=[{
            "name": "doc.pdf",
            "mime_type": "application/pdf",
            "size_bytes": 100,
            "content_b64": base64.b64encode(b"%PDF-1.4").decode(),
        }],
        chat_history=[],
    )
    db_session.add(task)
    await db_session.commit()

    processor = TaskProcessor(task.id, db_session)
    assert processor._parse_xlsx_items(task) == []


# ---------------------------------------------------------------------------
# Batching tests
# ---------------------------------------------------------------------------


async def test_25_items_produce_3_claude_calls(db_session, task_25):
    """25 items split into batches of 10 → ceil(25/10) = 3 Claude calls."""
    processor = TaskProcessor(task_25.id, db_session)

    call_count = 0

    async def counting_claude(messages, **kwargs):
        nonlocal call_count
        call_count += 1
        return _priced_response(call_count)

    with (
        patch("app.services.task_processor.call_claude", side_effect=counting_claude),
        patch("app.services.task_processor.generate_smeta", return_value=b"<excel>"),
        patch("app.services.task_processor.price_service", _mock_price()),
    ):
        await processor._handle_smeta_from_list(task_25)

    assert call_count == 3, f"Expected 3 Claude calls, got {call_count}"


async def test_10_items_produce_1_claude_call(db_session, task_10):
    """Exactly 10 items → exactly 1 batch → 1 Claude call."""
    processor = TaskProcessor(task_10.id, db_session)
    call_count = 0

    async def counting_claude(messages, **kwargs):
        nonlocal call_count
        call_count += 1
        return _priced_response(call_count)

    with (
        patch("app.services.task_processor.call_claude", side_effect=counting_claude),
        patch("app.services.task_processor.generate_smeta", return_value=b"<excel>"),
        patch("app.services.task_processor.price_service", _mock_price()),
    ):
        await processor._handle_smeta_from_list(task_10)

    assert call_count == 1


async def test_batch_content_limited_to_batch_size(db_session, task_25):
    """Each individual Claude call receives at most SMETA_BATCH_SIZE items."""
    from app.services.task_processor import SMETA_BATCH_SIZE
    processor = TaskProcessor(task_25.id, db_session)
    batch_sizes: list[int] = []

    async def inspecting_claude(messages, **kwargs):
        content = messages[0]["content"]
        # The items JSON block is pretty-printed; find it by locating "items" key
        start = content.index('"items"')
        # Walk back to find the opening '{'
        brace_pos = content.rindex('{', 0, start)
        snippet = content[brace_pos:]
        # Find matching closing brace
        depth, end = 0, 0
        for i, ch in enumerate(snippet):
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        data = json.loads(snippet[:end])
        batch_sizes.append(len(data["items"]))
        return _priced_response(len(batch_sizes))

    with (
        patch("app.services.task_processor.call_claude", side_effect=inspecting_claude),
        patch("app.services.task_processor.generate_smeta", return_value=b"<excel>"),
        patch("app.services.task_processor.price_service", _mock_price()),
    ):
        await processor._handle_smeta_from_list(task_25)

    assert all(s <= SMETA_BATCH_SIZE for s in batch_sizes), (
        f"A batch exceeded SMETA_BATCH_SIZE={SMETA_BATCH_SIZE}: {batch_sizes}"
    )


async def test_results_combined_in_batch_order(db_session, task_25):
    """Items from all batches appear in generate_smeta in the original batch order."""
    processor = TaskProcessor(task_25.id, db_session)
    batch_num = 0

    async def ordered_claude(messages, **kwargs):
        nonlocal batch_num
        batch_num += 1
        return _priced_response(batch_num)

    captured: list[dict] = []

    def capturing_generate_smeta(items):
        captured.extend(items)
        return b"<excel>"

    with (
        patch("app.services.task_processor.call_claude", side_effect=ordered_claude),
        patch("app.services.task_processor.generate_smeta", side_effect=capturing_generate_smeta),
        patch("app.services.task_processor.price_service", _mock_price()),
    ):
        await processor._handle_smeta_from_list(task_25)

    names = [item["name"] for item in captured]
    assert names[0].startswith("Batch1_"), f"First item not from batch 1: {names[0]}"
    assert names[1].startswith("Batch2_"), f"Second item not from batch 2: {names[1]}"
    assert names[2].startswith("Batch3_"), f"Third item not from batch 3: {names[2]}"


# ---------------------------------------------------------------------------
# Progress message tests
# ---------------------------------------------------------------------------


async def test_progress_message_set_for_each_batch(db_session, task_25):
    """Progress messages include 'батч N из 3' for each of the 3 batches."""
    processor = TaskProcessor(task_25.id, db_session)
    recorded: list[str] = []
    original_update = processor.update_progress

    async def tracking_update(msg: str) -> None:
        recorded.append(msg)
        await original_update(msg)

    processor.update_progress = tracking_update  # type: ignore[method-assign]

    call_num = 0

    async def mock_claude(messages, **kwargs):
        nonlocal call_num
        call_num += 1
        return _priced_response(call_num)

    with (
        patch("app.services.task_processor.call_claude", side_effect=mock_claude),
        patch("app.services.task_processor.generate_smeta", return_value=b"<excel>"),
        patch("app.services.task_processor.price_service", _mock_price()),
    ):
        await processor._handle_smeta_from_list(task_25)

    batch_msgs = [m for m in recorded if "батч" in m.lower()]
    assert len(batch_msgs) >= 3, f"Expected ≥3 batch messages, got: {batch_msgs}"
    assert any("1 из 3" in m for m in batch_msgs), f"No '1 из 3' in {batch_msgs}"
    assert any("2 из 3" in m for m in batch_msgs), f"No '2 из 3' in {batch_msgs}"
    assert any("3 из 3" in m for m in batch_msgs), f"No '3 из 3' in {batch_msgs}"


async def test_progress_message_visible_in_task_status(db_session, task_25):
    """During processing, task.progress_message in DB contains batch info."""
    processor = TaskProcessor(task_25.id, db_session)
    seen_batch_messages: list[str] = []
    original_update = processor.update_progress

    async def tracking_update(msg: str) -> None:
        await original_update(msg)
        if "батч" in msg.lower():
            seen_batch_messages.append(msg)

    processor.update_progress = tracking_update  # type: ignore[method-assign]

    call_num = 0

    async def mock_claude(messages, **kwargs):
        nonlocal call_num
        call_num += 1
        return _priced_response(call_num)

    with (
        patch("app.services.task_processor.call_claude", side_effect=mock_claude),
        patch("app.services.task_processor.generate_smeta", return_value=b"<excel>"),
        patch("app.services.task_processor.price_service", _mock_price()),
    ):
        await processor._handle_smeta_from_list(task_25)

    assert len(seen_batch_messages) >= 3


# ---------------------------------------------------------------------------
# Timeout tests
# ---------------------------------------------------------------------------


async def test_timed_out_batch_is_skipped_task_continues(db_session, task_20):
    """If batch 2 times out, its original items are kept and batch processing continues."""
    processor = TaskProcessor(task_20.id, db_session)
    call_num = 0

    async def selective_slow_claude(messages, **kwargs):
        nonlocal call_num
        call_num += 1
        if call_num == 2:
            await asyncio.sleep(10)  # Much longer than patched timeout
        return _priced_response(call_num)

    captured: list[dict] = []

    def capture_smeta(items):
        captured.extend(items)
        return b"<excel>"

    with (
        patch("app.services.task_processor.call_claude", side_effect=selective_slow_claude),
        patch("app.services.task_processor.SMETA_BATCH_TIMEOUT_SECS", 0.05),
        patch("app.services.task_processor.generate_smeta", side_effect=capture_smeta),
        patch("app.services.task_processor.price_service", _mock_price()),
    ):
        # Task must complete without raising
        await processor._handle_smeta_from_list(task_20)

    # 11 items total: batch 1 succeeds (Claude returns 1 mock item) + batch 2 times out (10 original items)
    assert len(captured) == 11, f"Expected 11 items in result, got {len(captured)}"


async def test_timed_out_batch_items_have_no_pricing(db_session, task_20):
    """Items from a timed-out batch do not have work_price set from Claude."""
    processor = TaskProcessor(task_20.id, db_session)
    call_num = 0

    async def selective_slow_claude(messages, **kwargs):
        nonlocal call_num
        call_num += 1
        if call_num == 2:
            await asyncio.sleep(10)
        return _priced_response(call_num)

    captured: list[dict] = []

    def capture_smeta(items):
        captured.extend(items)
        return b"<excel>"

    with (
        patch("app.services.task_processor.call_claude", side_effect=selective_slow_claude),
        patch("app.services.task_processor.SMETA_BATCH_TIMEOUT_SECS", 0.05),
        patch("app.services.task_processor.generate_smeta", side_effect=capture_smeta),
        patch("app.services.task_processor.price_service", _mock_price()),
    ):
        await processor._handle_smeta_from_list(task_20)

    # Batch 1 succeeds: Claude mock returns 1 priced item (work_price=100)
    assert captured[0].get("work_price") == 100, (
        "First item (from successful batch 1) should be priced"
    )

    # Batch 2 timed out: 10 original items kept without pricing
    batch2_items = captured[1:]
    assert len(batch2_items) == 10, f"Expected 10 unpriced items from batch 2, got {len(batch2_items)}"
    assert all(item.get("work_price") is None for item in batch2_items), (
        "Batch 2 items should be unpriced (timeout)"
    )


async def test_timeout_warning_is_logged(db_session, task_20, capsys):
    """A warning is logged when a batch times out."""
    processor = TaskProcessor(task_20.id, db_session)
    call_num = 0

    async def selective_slow_claude(messages, **kwargs):
        nonlocal call_num
        call_num += 1
        if call_num == 1:
            await asyncio.sleep(10)
        return _priced_response(call_num)

    with (
        patch("app.services.task_processor.call_claude", side_effect=selective_slow_claude),
        patch("app.services.task_processor.SMETA_BATCH_TIMEOUT_SECS", 0.05),
        patch("app.services.task_processor.generate_smeta", return_value=b"<excel>"),
        patch("app.services.task_processor.price_service", _mock_price()),
    ):
        await processor._handle_smeta_from_list(task_20)

    # structlog writes to stdout; verify warning message appears
    output = capsys.readouterr().out
    assert "timed out" in output.lower() or "timeout" in output.lower(), (
        f"Expected timeout warning in stdout, got: {output[:500]}"
    )


# ---------------------------------------------------------------------------
# Result persistence tests
# ---------------------------------------------------------------------------


async def test_result_saved_to_db(db_session, task_25):
    """After completion, one TaskResult row with 'Смета.xlsx' is in the DB."""
    processor = TaskProcessor(task_25.id, db_session)
    call_num = 0

    async def mock_claude(messages, **kwargs):
        nonlocal call_num
        call_num += 1
        return _priced_response(call_num)

    with (
        patch("app.services.task_processor.call_claude", side_effect=mock_claude),
        patch("app.services.task_processor.generate_smeta", return_value=b"<final-excel>"),
        patch("app.services.task_processor.price_service", _mock_price()),
    ):
        await processor._handle_smeta_from_list(task_25)

    rows = (
        await db_session.execute(
            select(TaskResult).where(TaskResult.task_id == task_25.id)
        )
    ).scalars().all()

    assert len(rows) == 1
    assert rows[0].file_name == "Смета.xlsx"
    assert rows[0].file_data == b"<final-excel>"


async def test_result_contains_all_items(db_session, task_25):
    """generate_smeta receives items from all 3 batches (total 3 priced items in test)."""
    processor = TaskProcessor(task_25.id, db_session)
    call_num = 0

    async def mock_claude(messages, **kwargs):
        nonlocal call_num
        call_num += 1
        return _priced_response(call_num)

    items_received: list[dict] = []

    def capture_smeta(items):
        items_received.extend(items)
        return b"<excel>"

    with (
        patch("app.services.task_processor.call_claude", side_effect=mock_claude),
        patch("app.services.task_processor.generate_smeta", side_effect=capture_smeta),
        patch("app.services.task_processor.price_service", _mock_price()),
    ):
        await processor._handle_smeta_from_list(task_25)

    # 3 batches × 1 item per batch in our mock
    assert len(items_received) == 3


# ---------------------------------------------------------------------------
# Dispatch test
# ---------------------------------------------------------------------------


async def test_smeta_from_list_dispatched_to_new_handler(db_session, task_25):
    """process() routes SMETA_FROM_LIST to _handle_smeta_from_list, not _handle_smeta."""
    processor = TaskProcessor(task_25.id, db_session)

    handler_called = False
    original = processor._handle_smeta_from_list

    async def spy(task):
        nonlocal handler_called
        handler_called = True
        await original(task)

    processor._handle_smeta_from_list = spy  # type: ignore[method-assign]
    call_num = 0

    async def mock_claude(messages, **kwargs):
        nonlocal call_num
        call_num += 1
        return _priced_response(call_num)

    with (
        patch("app.services.task_processor.call_claude", side_effect=mock_claude),
        patch("app.services.task_processor.generate_smeta", return_value=b"<excel>"),
        patch("app.services.task_processor.price_service", _mock_price()),
    ):
        await processor.process()

    assert handler_called, "_handle_smeta_from_list was not invoked by process()"
