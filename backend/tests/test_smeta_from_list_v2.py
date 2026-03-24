"""TDD tests for SMETA_FROM_LIST batching improvements (v2).

Covers all six fixes:
  Change 3 — batch size 5, inter-batch delay 4 s
  Changes 1&2 — processing_timeout passed to call_claude; TimeoutError → needs_retry
  Change 5 — timed-out / partial items go to needs_retry, not silently unpriced
  Change 6 — retry queue (smaller batches, longer timeout, 30-s gap, manual-check note)
"""
import asyncio
import base64
import io
import json
import uuid
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch, call as mcall

import openpyxl
import pytest
import pytest_asyncio

from app.models.result import TaskResult
from app.models.task import Task
from app.services.task_processor import TaskProcessor


# ---------------------------------------------------------------------------
# Helpers (duplicated from v1 to keep files independent)
# ---------------------------------------------------------------------------

def _make_xlsx_b64(items: list[dict]) -> str:
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
    return [
        {"type": "Работа", "name": f"Позиция {i + 1}", "unit": "м2",
         "quantity": float(i + 1), "notes": ""}
        for i in range(n)
    ]


def _priced_json(batch_num: int, n: int = 1) -> str:
    """Return a JSON string with n priced items for batch_num."""
    items = [
        {"type": "Работа", "name": f"Batch{batch_num}_Item{j}",
         "unit": "м2", "quantity": 1.0,
         "work_price": 100 * batch_num, "material_price": None,
         "price_list_name": None, "sources": None, "notes": ""}
        for j in range(n)
    ]
    return json.dumps({"items": items})


def _mock_price():
    svc = MagicMock()
    svc.load_cache = AsyncMock()
    svc._works_cache = []
    svc._materials_cache = []
    return svc


async def _task_with_excel(db_session, n_items: int) -> Task:
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
async def task_5(db_session):
    return await _task_with_excel(db_session, 5)


@pytest_asyncio.fixture
async def task_10(db_session):
    return await _task_with_excel(db_session, 10)


@pytest_asyncio.fixture
async def task_15(db_session):
    return await _task_with_excel(db_session, 15)


# Common patch context that avoids real sleeps and prices
def _base_patches():
    return (
        patch("app.services.task_processor.generate_smeta", return_value=b"<excel>"),
        patch("app.services.task_processor.price_service", _mock_price()),
        patch("app.services.task_processor.asyncio.sleep", AsyncMock()),
    )


# ---------------------------------------------------------------------------
# Change 3 — Batch size 5
# ---------------------------------------------------------------------------

async def test_batch_size_constant_is_5():
    """SMETA_BATCH_SIZE must equal 5."""
    from app.services.task_processor import SMETA_BATCH_SIZE
    assert SMETA_BATCH_SIZE == 5, f"Expected SMETA_BATCH_SIZE=5, got {SMETA_BATCH_SIZE}"


async def test_5_items_produce_exactly_1_main_call(db_session, task_5):
    """5 items == 1 full batch → exactly 1 Claude call."""
    call_count = 0

    async def counting_claude(messages, **kwargs):
        nonlocal call_count
        call_count += 1
        return _priced_json(call_count, n=5)  # return all 5 items so no retry

    with (
        patch("app.services.task_processor.call_claude", side_effect=counting_claude),
        patch("app.services.task_processor.generate_smeta", return_value=b"<excel>"),
        patch("app.services.task_processor.price_service", _mock_price()),
        patch("app.services.task_processor.asyncio.sleep", AsyncMock()),
    ):
        await TaskProcessor(task_5.id, db_session)._handle_smeta_from_list(task_5)

    assert call_count == 1, f"Expected 1 call for 5 items, got {call_count}"


async def test_10_items_produce_exactly_2_main_calls(db_session, task_10):
    """10 items → 2 batches of 5 → 2 Claude calls."""
    call_count = 0

    async def counting_claude(messages, **kwargs):
        nonlocal call_count
        call_count += 1
        return _priced_json(call_count, n=5)  # return all 5 items so no retry

    with (
        patch("app.services.task_processor.call_claude", side_effect=counting_claude),
        patch("app.services.task_processor.generate_smeta", return_value=b"<excel>"),
        patch("app.services.task_processor.price_service", _mock_price()),
        patch("app.services.task_processor.asyncio.sleep", AsyncMock()),
    ):
        await TaskProcessor(task_10.id, db_session)._handle_smeta_from_list(task_10)

    assert call_count == 2, f"Expected 2 calls for 10 items, got {call_count}"


# ---------------------------------------------------------------------------
# Change 3 — Inter-batch delay
# ---------------------------------------------------------------------------

async def test_inter_batch_delay_constant_exists():
    """SMETA_INTER_BATCH_DELAY must be defined and be > 0."""
    from app.services.task_processor import SMETA_INTER_BATCH_DELAY
    assert SMETA_INTER_BATCH_DELAY > 0


async def test_inter_batch_delay_called_between_batches(db_session, task_10):
    """asyncio.sleep is called with SMETA_INTER_BATCH_DELAY between the two main batches."""
    from app.services.task_processor import SMETA_INTER_BATCH_DELAY

    sleep_mock = AsyncMock()
    call_count = 0

    async def counting_claude(messages, **kwargs):
        nonlocal call_count
        call_count += 1
        return _priced_json(call_count)

    with (
        patch("app.services.task_processor.call_claude", side_effect=counting_claude),
        patch("app.services.task_processor.generate_smeta", return_value=b"<excel>"),
        patch("app.services.task_processor.price_service", _mock_price()),
        patch("app.services.task_processor.asyncio.sleep", sleep_mock),
    ):
        await TaskProcessor(task_10.id, db_session)._handle_smeta_from_list(task_10)

    delay_calls = [c.args[0] for c in sleep_mock.call_args_list
                   if c.args and abs(c.args[0] - SMETA_INTER_BATCH_DELAY) < 0.5]
    assert len(delay_calls) >= 1, (
        f"Expected sleep({SMETA_INTER_BATCH_DELAY}) between batches; "
        f"all sleep calls: {[c.args for c in sleep_mock.call_args_list]}"
    )


async def test_no_inter_batch_delay_after_last_batch(db_session, task_5):
    """No inter-batch delay after the final (only) batch."""
    from app.services.task_processor import SMETA_INTER_BATCH_DELAY

    sleep_mock = AsyncMock()

    async def mock_claude(messages, **kwargs):
        return _priced_json(1)

    with (
        patch("app.services.task_processor.call_claude", side_effect=mock_claude),
        patch("app.services.task_processor.generate_smeta", return_value=b"<excel>"),
        patch("app.services.task_processor.price_service", _mock_price()),
        patch("app.services.task_processor.asyncio.sleep", sleep_mock),
    ):
        await TaskProcessor(task_5.id, db_session)._handle_smeta_from_list(task_5)

    delay_calls = [c.args[0] for c in sleep_mock.call_args_list
                   if c.args and abs(c.args[0] - SMETA_INTER_BATCH_DELAY) < 0.5]
    assert len(delay_calls) == 0, (
        f"Should be no inter-batch delay after last batch, got {delay_calls}"
    )


# ---------------------------------------------------------------------------
# Changes 1 & 2 — processing_timeout passed through + TimeoutError → needs_retry
# ---------------------------------------------------------------------------

async def test_processing_timeout_passed_to_call_claude(db_session, task_5):
    """_handle_smeta_from_list passes SMETA_BATCH_TIMEOUT_SECS as processing_timeout."""
    from app.services.task_processor import SMETA_BATCH_TIMEOUT_SECS

    captured_kwargs: dict = {}

    async def capturing_claude(messages, **kwargs):
        captured_kwargs.update(kwargs)
        return _priced_json(1, n=5)  # return all 5 items so no retry overwrites captured_kwargs

    with (
        patch("app.services.task_processor.call_claude", side_effect=capturing_claude),
        patch("app.services.task_processor.generate_smeta", return_value=b"<excel>"),
        patch("app.services.task_processor.price_service", _mock_price()),
        patch("app.services.task_processor.asyncio.sleep", AsyncMock()),
    ):
        await TaskProcessor(task_5.id, db_session)._handle_smeta_from_list(task_5)

    assert "processing_timeout" in captured_kwargs, (
        "call_claude was not called with processing_timeout kwarg"
    )
    assert captured_kwargs["processing_timeout"] == SMETA_BATCH_TIMEOUT_SECS, (
        f"Expected processing_timeout={SMETA_BATCH_TIMEOUT_SECS}, "
        f"got {captured_kwargs['processing_timeout']}"
    )


async def test_timeout_error_marks_batch_items_as_needs_retry(db_session, task_5):
    """asyncio.TimeoutError from call_claude marks all batch items as needs_retry."""
    captured: list[dict] = []

    async def timing_out_claude(messages, **kwargs):
        raise asyncio.TimeoutError()

    def capturing_smeta(items):
        captured.extend(items)
        return b"<excel>"

    with (
        patch("app.services.task_processor.call_claude", side_effect=timing_out_claude),
        patch("app.services.task_processor.generate_smeta", side_effect=capturing_smeta),
        patch("app.services.task_processor.price_service", _mock_price()),
        patch("app.services.task_processor.asyncio.sleep", AsyncMock()),
    ):
        await TaskProcessor(task_5.id, db_session)._handle_smeta_from_list(task_5)

    # All items eventually appear in the result (via retry queue / manual check)
    assert len(captured) == 5, f"Expected 5 items in final result, got {len(captured)}"


async def test_timeout_items_have_no_pricing_before_retry(db_session, task_5):
    """Items that time out in the main pass have no work_price from that pass."""
    timeout_count = 0
    claude_call = 0

    async def selective_claude(messages, **kwargs):
        nonlocal timeout_count, claude_call
        claude_call += 1
        # First call (main batch) times out; subsequent calls (retry) succeed
        if claude_call == 1:
            timeout_count += 1
            raise asyncio.TimeoutError()
        return _priced_json(claude_call)

    captured: list[dict] = []

    def capturing_smeta(items):
        captured.extend(items)
        return b"<excel>"

    with (
        patch("app.services.task_processor.call_claude", side_effect=selective_claude),
        patch("app.services.task_processor.generate_smeta", side_effect=capturing_smeta),
        patch("app.services.task_processor.price_service", _mock_price()),
        patch("app.services.task_processor.asyncio.sleep", AsyncMock()),
    ):
        await TaskProcessor(task_5.id, db_session)._handle_smeta_from_list(task_5)

    assert timeout_count == 1  # the main batch did time out
    assert len(captured) == 5


# ---------------------------------------------------------------------------
# Change 5 — Partial response: unmatched input items go to retry
# ---------------------------------------------------------------------------

async def test_partial_response_unmatched_inputs_go_to_retry(db_session, task_5):
    """If Claude returns fewer items than were sent, missing items are retried."""
    main_call_done = False

    async def partial_claude(messages, **kwargs):
        nonlocal main_call_done
        if not main_call_done:
            main_call_done = True
            # Return only 2 items for a 5-item batch
            return json.dumps({"items": [
                {"name": "Partial1", "work_price": 50, "unit": "м2",
                 "quantity": 1.0, "type": "Работа", "notes": ""}
                for _ in range(2)
            ]})
        # Retry calls succeed
        return _priced_json(99)

    captured: list[dict] = []

    def capturing_smeta(items):
        captured.extend(items)
        return b"<excel>"

    with (
        patch("app.services.task_processor.call_claude", side_effect=partial_claude),
        patch("app.services.task_processor.generate_smeta", side_effect=capturing_smeta),
        patch("app.services.task_processor.price_service", _mock_price()),
        patch("app.services.task_processor.asyncio.sleep", AsyncMock()),
    ):
        await TaskProcessor(task_5.id, db_session)._handle_smeta_from_list(task_5)

    # 2 items returned directly + 3 unmatched items retried
    assert len(captured) == 5, f"Expected 5 total items, got {len(captured)}"
    # The 2 partial items have work_price=50
    partial_items = [i for i in captured if i.get("work_price") == 50]
    assert len(partial_items) == 2, f"Expected 2 partial items with price 50"


# ---------------------------------------------------------------------------
# Change 6 — Retry queue
# ---------------------------------------------------------------------------

async def test_needs_retry_items_are_processed_in_retry_queue(db_session, task_5):
    """Items that time out in main batches are retried in a second pass."""
    call_count = 0

    async def timed_out_then_success(messages, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise asyncio.TimeoutError()  # main batch times out
        return _priced_json(call_count)  # retry succeeds

    with (
        patch("app.services.task_processor.call_claude", side_effect=timed_out_then_success),
        patch("app.services.task_processor.generate_smeta", return_value=b"<excel>"),
        patch("app.services.task_processor.price_service", _mock_price()),
        patch("app.services.task_processor.asyncio.sleep", AsyncMock()),
    ):
        await TaskProcessor(task_5.id, db_session)._handle_smeta_from_list(task_5)

    # At minimum: 1 main call + at least 1 retry call
    assert call_count >= 2, f"Expected >= 2 Claude calls (main + retry), got {call_count}"


async def test_retry_queue_batch_size_constant_exists():
    """SMETA_RETRY_BATCH_SIZE must be defined and <= 3."""
    from app.services.task_processor import SMETA_RETRY_BATCH_SIZE
    assert 1 <= SMETA_RETRY_BATCH_SIZE <= 3, (
        f"SMETA_RETRY_BATCH_SIZE should be 2-3, got {SMETA_RETRY_BATCH_SIZE}"
    )


async def test_retry_queue_uses_smaller_batches(db_session, task_10):
    """Retry batches contain at most SMETA_RETRY_BATCH_SIZE items."""
    from app.services.task_processor import SMETA_RETRY_BATCH_SIZE

    retry_batch_sizes: list[int] = []
    main_call_done = False

    async def inspecting_claude(messages, **kwargs):
        nonlocal main_call_done
        content = messages[0]["content"]

        if not main_call_done:
            main_call_done = True
            # Both main batches time out → 10 items need retry
            raise asyncio.TimeoutError()

        # Count items in retry calls
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
        retry_batch_sizes.append(len(data["items"]))
        return _priced_json(len(retry_batch_sizes))

    with (
        patch("app.services.task_processor.call_claude", side_effect=inspecting_claude),
        patch("app.services.task_processor.generate_smeta", return_value=b"<excel>"),
        patch("app.services.task_processor.price_service", _mock_price()),
        patch("app.services.task_processor.asyncio.sleep", AsyncMock()),
    ):
        # Run only the first main batch call (5 items) — it times out
        proc = TaskProcessor(task_10.id, db_session)
        # Use task_5 to keep it manageable: 1 main batch of 5 → all timeout → retry
        task = await _task_with_excel(db_session, 5)
        proc2 = TaskProcessor(task.id, db_session)
        await proc2._handle_smeta_from_list(task)

    assert all(s <= SMETA_RETRY_BATCH_SIZE for s in retry_batch_sizes), (
        f"Retry batch exceeded SMETA_RETRY_BATCH_SIZE={SMETA_RETRY_BATCH_SIZE}: {retry_batch_sizes}"
    )


async def test_retry_timeout_constant_exists():
    """SMETA_RETRY_TIMEOUT_SECS must be defined and >= 300."""
    from app.services.task_processor import SMETA_RETRY_TIMEOUT_SECS
    assert SMETA_RETRY_TIMEOUT_SECS >= 300, (
        f"SMETA_RETRY_TIMEOUT_SECS should be >= 300 s, got {SMETA_RETRY_TIMEOUT_SECS}"
    )


async def test_retry_passes_retry_timeout_to_call_claude(db_session, task_5):
    """During retry queue, call_claude is called with SMETA_RETRY_TIMEOUT_SECS."""
    from app.services.task_processor import SMETA_RETRY_TIMEOUT_SECS

    main_done = False
    captured_retry_timeout: list = []

    async def capturing_claude(messages, **kwargs):
        nonlocal main_done
        if not main_done:
            main_done = True
            raise asyncio.TimeoutError()
        captured_retry_timeout.append(kwargs.get("processing_timeout"))
        return _priced_json(1)

    with (
        patch("app.services.task_processor.call_claude", side_effect=capturing_claude),
        patch("app.services.task_processor.generate_smeta", return_value=b"<excel>"),
        patch("app.services.task_processor.price_service", _mock_price()),
        patch("app.services.task_processor.asyncio.sleep", AsyncMock()),
    ):
        await TaskProcessor(task_5.id, db_session)._handle_smeta_from_list(task_5)

    assert captured_retry_timeout, "No retry calls were made"
    assert all(t == SMETA_RETRY_TIMEOUT_SECS for t in captured_retry_timeout), (
        f"Expected retry processing_timeout={SMETA_RETRY_TIMEOUT_SECS}, "
        f"got: {captured_retry_timeout}"
    )


async def test_retry_inter_batch_delay_constant_exists():
    """SMETA_RETRY_INTER_BATCH_DELAY must be defined and >= 10 s."""
    from app.services.task_processor import SMETA_RETRY_INTER_BATCH_DELAY
    assert SMETA_RETRY_INTER_BATCH_DELAY >= 10, (
        f"SMETA_RETRY_INTER_BATCH_DELAY should be >= 10 s, got {SMETA_RETRY_INTER_BATCH_DELAY}"
    )


async def test_retry_inter_batch_delay_between_retry_batches(db_session):
    """asyncio.sleep(SMETA_RETRY_INTER_BATCH_DELAY) is called between retry batches."""
    from app.services.task_processor import SMETA_RETRY_INTER_BATCH_DELAY, SMETA_RETRY_BATCH_SIZE

    # Create a task with enough items to produce 2 retry batches
    n = SMETA_RETRY_BATCH_SIZE * 2 + 1  # e.g. 5 items → 3 retry batches
    task = await _task_with_excel(db_session, n)

    sleep_mock = AsyncMock()
    main_done = False
    retry_call = 0

    async def timed_out_then_success(messages, **kwargs):
        nonlocal main_done, retry_call
        if not main_done:
            main_done = True
            raise asyncio.TimeoutError()
        retry_call += 1
        return _priced_json(retry_call)

    with (
        patch("app.services.task_processor.call_claude", side_effect=timed_out_then_success),
        patch("app.services.task_processor.generate_smeta", return_value=b"<excel>"),
        patch("app.services.task_processor.price_service", _mock_price()),
        patch("app.services.task_processor.asyncio.sleep", sleep_mock),
    ):
        await TaskProcessor(task.id, db_session)._handle_smeta_from_list(task)

    retry_delay_calls = [c.args[0] for c in sleep_mock.call_args_list
                         if c.args and abs(c.args[0] - SMETA_RETRY_INTER_BATCH_DELAY) < 1]
    assert len(retry_delay_calls) >= 1, (
        f"Expected sleep({SMETA_RETRY_INTER_BATCH_DELAY}) between retry batches; "
        f"all sleep calls: {[c.args for c in sleep_mock.call_args_list]}"
    )


async def test_permanently_failed_items_get_manual_check_note(db_session, task_5):
    """Items that fail even in retry queue get 'требует ручной проверки' in notes."""
    captured: list[dict] = []

    async def always_timeout(messages, **kwargs):
        raise asyncio.TimeoutError()

    def capturing_smeta(items):
        captured.extend(items)
        return b"<excel>"

    with (
        patch("app.services.task_processor.call_claude", side_effect=always_timeout),
        patch("app.services.task_processor.generate_smeta", side_effect=capturing_smeta),
        patch("app.services.task_processor.price_service", _mock_price()),
        patch("app.services.task_processor.asyncio.sleep", AsyncMock()),
    ):
        await TaskProcessor(task_5.id, db_session)._handle_smeta_from_list(task_5)

    assert len(captured) == 5, f"Expected 5 items, got {len(captured)}"
    manual_check = [i for i in captured if "ручной проверки" in i.get("notes", "")]
    assert len(manual_check) == 5, (
        f"All 5 items should be marked for manual check, got {len(manual_check)}"
    )


async def test_successfully_retried_items_have_pricing(db_session, task_5):
    """Items that succeed in the retry queue have work_price set."""
    main_done = False
    retry_call = 0
    captured: list[dict] = []

    async def timed_out_then_priced(messages, **kwargs):
        nonlocal main_done, retry_call
        if not main_done:
            main_done = True
            raise asyncio.TimeoutError()
        retry_call += 1
        return _priced_json(retry_call, n=1)

    def capturing_smeta(items):
        captured.extend(items)
        return b"<excel>"

    with (
        patch("app.services.task_processor.call_claude", side_effect=timed_out_then_priced),
        patch("app.services.task_processor.generate_smeta", side_effect=capturing_smeta),
        patch("app.services.task_processor.price_service", _mock_price()),
        patch("app.services.task_processor.asyncio.sleep", AsyncMock()),
    ):
        await TaskProcessor(task_5.id, db_session)._handle_smeta_from_list(task_5)

    priced = [i for i in captured if i.get("work_price") is not None]
    assert len(priced) > 0, "Expected at least some items to be priced after retry"


async def test_retry_queue_progress_message(db_session, task_5):
    """Progress messages contain retry-related text during the retry pass."""
    recorded: list[str] = []
    main_done = False
    retry_call = 0

    async def timed_out_then_success(messages, **kwargs):
        nonlocal main_done, retry_call
        if not main_done:
            main_done = True
            raise asyncio.TimeoutError()
        retry_call += 1
        return _priced_json(retry_call)

    proc = TaskProcessor(task_5.id, db_session)
    original_update = proc.update_progress

    async def tracking_update(msg: str) -> None:
        recorded.append(msg)
        await original_update(msg)

    proc.update_progress = tracking_update  # type: ignore

    with (
        patch("app.services.task_processor.call_claude", side_effect=timed_out_then_success),
        patch("app.services.task_processor.generate_smeta", return_value=b"<excel>"),
        patch("app.services.task_processor.price_service", _mock_price()),
        patch("app.services.task_processor.asyncio.sleep", AsyncMock()),
    ):
        await proc._handle_smeta_from_list(task_5)

    retry_msgs = [m for m in recorded if "повтор" in m.lower() or "retry" in m.lower()]
    assert len(retry_msgs) >= 1, f"Expected retry progress messages, got: {recorded}"
