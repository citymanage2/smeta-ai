"""TDD tests for SMETA_FROM_LIST batching.

Required behaviour (updated for v2 batch size = 5):
- Items list is split into batches of SMETA_BATCH_SIZE (5).
- Each batch gets its own Claude API call.
- Results from all batches are combined in order.
- Progress message is updated after each batch (text contains "батч N из M").
- If a batch's Claude call raises asyncio.TimeoutError, that batch's items are
  marked needs_retry and processed in a retry queue.
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
# _parse_xlsx_items tests  (unchanged)
# ---------------------------------------------------------------------------


async def test_parse_xlsx_items_extracts_correct_items(db_session):
    """Items are read from the Excel with correct field mapping."""
    items = [
        {"type": "Работа", "name": "Кладка кирпича", "unit": "м3", "quantity": 15.5, "notes": "основная"},
        {"type": "Материал", "name": "Кирпич М150", "unit": "шт", "quantity": 10000.0, "notes": ""},
    ]
    task = await _task_with_excel(db_session, 0)
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
# Batching tests  (updated for SMETA_BATCH_SIZE = 5)
# ---------------------------------------------------------------------------


async def test_25_items_produce_5_claude_calls(db_session, task_25):
    """25 items split into batches of 5 → ceil(25/5) = 5 main Claude calls."""
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
        patch("app.services.task_processor.asyncio.sleep", AsyncMock()),
        patch.object(TaskProcessor, "_process_retry_queue", AsyncMock(return_value=[])),
    ):
        await processor._handle_smeta_from_list(task_25)

    assert call_count == 5, f"Expected 5 Claude calls for 25 items, got {call_count}"


async def test_10_items_produce_2_claude_calls(db_session, task_10):
    """10 items → 2 batches of 5 → 2 main Claude calls."""
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
        patch("app.services.task_processor.asyncio.sleep", AsyncMock()),
        patch.object(TaskProcessor, "_process_retry_queue", AsyncMock(return_value=[])),
    ):
        await processor._handle_smeta_from_list(task_10)

    assert call_count == 2, f"Expected 2 Claude calls for 10 items, got {call_count}"


async def test_batch_content_limited_to_batch_size(db_session, task_25):
    """Each individual Claude call receives at most SMETA_BATCH_SIZE items."""
    from app.services.task_processor import SMETA_BATCH_SIZE
    processor = TaskProcessor(task_25.id, db_session)
    batch_sizes: list[int] = []

    async def inspecting_claude(messages, **kwargs):
        content = messages[0]["content"]
        start = content.index('"items"')
        brace_pos = content.rindex('{', 0, start)
        snippet = content[brace_pos:]
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
        patch("app.services.task_processor.asyncio.sleep", AsyncMock()),
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
        patch("app.services.task_processor.asyncio.sleep", AsyncMock()),
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
    """Progress messages include 'батч N из 5' for each of the 5 batches."""
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
        patch("app.services.task_processor.asyncio.sleep", AsyncMock()),
    ):
        await processor._handle_smeta_from_list(task_25)

    batch_msgs = [m for m in recorded if "батч" in m.lower()]
    assert len(batch_msgs) >= 5, f"Expected ≥5 batch messages, got: {batch_msgs}"
    assert any("1 из 5" in m for m in batch_msgs), f"No '1 из 5' in {batch_msgs}"
    assert any("2 из 5" in m for m in batch_msgs), f"No '2 из 5' in {batch_msgs}"
    assert any("5 из 5" in m for m in batch_msgs), f"No '5 из 5' in {batch_msgs}"


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
        patch("app.services.task_processor.asyncio.sleep", AsyncMock()),
    ):
        await processor._handle_smeta_from_list(task_25)

    assert len(seen_batch_messages) >= 5


# ---------------------------------------------------------------------------
# Timeout tests  (updated: TimeoutError raised directly; retry queue is exercised)
# ---------------------------------------------------------------------------


async def test_timed_out_batch_is_skipped_task_continues(db_session, task_20):
    """If one batch times out, the task still completes (no unhandled exception)."""
    processor = TaskProcessor(task_20.id, db_session)
    call_num = 0

    async def selective_timeout_claude(messages, **kwargs):
        nonlocal call_num
        call_num += 1
        if call_num == 2:
            raise asyncio.TimeoutError()  # second main batch times out
        return _priced_response(call_num)

    with (
        patch("app.services.task_processor.call_claude", side_effect=selective_timeout_claude),
        patch("app.services.task_processor.generate_smeta", return_value=b"<excel>"),
        patch("app.services.task_processor.price_service", _mock_price()),
        patch("app.services.task_processor.asyncio.sleep", AsyncMock()),
    ):
        # Must complete without raising
        await processor._handle_smeta_from_list(task_20)


async def test_timed_out_batch_items_eventually_in_result(db_session, task_20):
    """Items from a timed-out batch appear in the final result (via retry queue)."""
    processor = TaskProcessor(task_20.id, db_session)
    call_num = 0
    captured: list[dict] = []

    async def timeout_then_succeed(messages, **kwargs):
        nonlocal call_num
        call_num += 1
        if call_num == 1:
            raise asyncio.TimeoutError()  # first batch times out
        return _priced_response(call_num)

    def capture_smeta(items):
        captured.extend(items)
        return b"<excel>"

    with (
        patch("app.services.task_processor.call_claude", side_effect=timeout_then_succeed),
        patch("app.services.task_processor.generate_smeta", side_effect=capture_smeta),
        patch("app.services.task_processor.price_service", _mock_price()),
        patch("app.services.task_processor.asyncio.sleep", AsyncMock()),
    ):
        await processor._handle_smeta_from_list(task_20)

    # All 20 items must appear in the final generate_smeta call
    assert len(captured) == 20, f"Expected 20 items in result, got {len(captured)}"


async def test_timeout_warning_is_logged(db_session, task_20, capsys):
    """A warning is logged when a batch times out."""
    processor = TaskProcessor(task_20.id, db_session)
    call_num = 0

    async def selective_timeout_claude(messages, **kwargs):
        nonlocal call_num
        call_num += 1
        if call_num == 1:
            raise asyncio.TimeoutError()
        return _priced_response(call_num)

    with (
        patch("app.services.task_processor.call_claude", side_effect=selective_timeout_claude),
        patch("app.services.task_processor.generate_smeta", return_value=b"<excel>"),
        patch("app.services.task_processor.price_service", _mock_price()),
        patch("app.services.task_processor.asyncio.sleep", AsyncMock()),
    ):
        await processor._handle_smeta_from_list(task_20)

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
        patch("app.services.task_processor.asyncio.sleep", AsyncMock()),
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
    """generate_smeta receives items from all 5 batches (total 5 priced items in test)."""
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
        patch("app.services.task_processor.asyncio.sleep", AsyncMock()),
    ):
        await processor._handle_smeta_from_list(task_25)

    # 5 main calls × 1 priced item + 20 retried items (10 batches × 2: 1 priced + 1 manual)
    assert len(items_received) == 25, f"Expected 25 items (all 25 inputs), got {len(items_received)}"


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
        patch("app.services.task_processor.asyncio.sleep", AsyncMock()),
    ):
        await processor.process()

    assert handler_called, "_handle_smeta_from_list was not invoked by process()"
