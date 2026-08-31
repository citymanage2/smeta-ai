"""
Фаза 3 — пауза при исчерпании баланса Anthropic API.

Контракт:
- claude_service бросает типизированный InsufficientBalanceError (подкласс
  RuntimeError) при 4xx с сообщением про credit balance — вместо голого
  RuntimeError, чтобы вызывающий код мог отличить «нет денег» от прочих ошибок.
- Чанковые retry-обёртки НЕ ретраят баланс-ошибку (ретрай не поможет), а
  сразу пробрасывают её вверх.
- TaskProcessor.process() ловит InsufficientBalanceError ОТДЕЛЬНО → статус
  `paused` (не `failed`), сохранённый чекпоинт (progress_data) не теряется.
- resume-эндпоинт допускает возобновление из статуса `paused`.

План: plans/2026-07-21-resume-and-balance-pause.md, Фаза 3.
"""
import sys
from unittest.mock import AsyncMock, MagicMock

import httpx2
import anthropic
import pytest
from sqlalchemy import select

sys.modules.setdefault("fitz", MagicMock())

from app.services.claude_service import (  # noqa: E402
    call_claude,
    InsufficientBalanceError,
)
from app.services.task_processor import TaskProcessor  # noqa: E402
from app.models.task import Task  # noqa: E402


def _make_credit_balance_error() -> anthropic.APIStatusError:
    """Fake 4xx APIStatusError with a 'credit balance' message (как у Anthropic)."""
    body = {
        "error": {
            "type": "invalid_request_error",
            "message": "Your credit balance is too low to access the Anthropic API.",
        }
    }
    raw = httpx2.Response(
        status_code=400,
        headers={"x-request-id": "test-req"},
        content=b'{"error": {"message": "Your credit balance is too low"}}',
        request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"),
    )
    return anthropic.APIStatusError("credit balance too low", response=raw, body=body)


# ---------------------------------------------------------------------------
# claude_service: типизированная ошибка баланса
# ---------------------------------------------------------------------------

def test_insufficient_balance_is_runtimeerror_subclass():
    # Обратная совместимость: существующие `except RuntimeError` продолжают ловить.
    assert issubclass(InsufficientBalanceError, RuntimeError)


async def test_credit_balance_4xx_raises_insufficient_balance(monkeypatch, patch_claude_create):
    async def fake_create(**kwargs):
        raise _make_credit_balance_error()

    patch_claude_create(fake_create)
    monkeypatch.setattr("app.services.claude_service.asyncio.sleep", AsyncMock())

    with pytest.raises(InsufficientBalanceError):
        await call_claude([{"role": "user", "content": "hi"}])


async def test_non_balance_4xx_not_wrapped(monkeypatch, patch_claude_create):
    """Прочие 4xx (не про баланс) НЕ превращаются в InsufficientBalanceError."""
    body = {"error": {"type": "invalid_request_error", "message": "bad request"}}
    raw = httpx2.Response(
        status_code=400,
        headers={},
        content=b'{"error": {"message": "bad request"}}',
        request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"),
    )

    async def fake_create(**kwargs):
        raise anthropic.APIStatusError("bad request", response=raw, body=body)

    patch_claude_create(fake_create)
    monkeypatch.setattr("app.services.claude_service.asyncio.sleep", AsyncMock())

    with pytest.raises(anthropic.APIStatusError):
        await call_claude([{"role": "user", "content": "hi"}])


# ---------------------------------------------------------------------------
# Чанковые retry-обёртки: баланс пробрасывается сразу, без ретраев
# ---------------------------------------------------------------------------

async def test_chunk_retry_reraises_balance_immediately(monkeypatch):
    p = TaskProcessor("tid-bal", db=MagicMock())
    inner = AsyncMock(side_effect=InsufficientBalanceError("no money"))
    p._call_claude_json = inner  # type: ignore[assignment]
    sleep_mock = AsyncMock()
    monkeypatch.setattr("app.services.task_processor.asyncio.sleep", sleep_mock)

    with pytest.raises(InsufficientBalanceError):
        await p._call_claude_json_with_retry([{"role": "user", "content": "x"}], system_prompt="s")

    # Ровно один вызов — ретраев не было; и sleep не вызывался.
    assert inner.await_count == 1
    assert sleep_mock.await_count == 0


# ---------------------------------------------------------------------------
# process(): баланс → paused, чекпоинт сохранён
# ---------------------------------------------------------------------------

PAUSE_TASK_ID = "d3000000-0000-0000-0000-000000000001"


async def test_process_pauses_on_insufficient_balance(seed_users, db_session):
    task = Task(owner_id=1, 
        id=PAUSE_TASK_ID,
        user_role="user",
        task_type="LIST_FROM_GRAND",
        status="processing",
        estimation_status="not_applicable",
        input_files=[],
        input_file_data=[],
        chat_history=[],
        progress_data={"chunks_done": 3},
    )
    db_session.add(task)
    await db_session.commit()

    processor = TaskProcessor(PAUSE_TASK_ID, db_session)
    processor._handle_list_from_grand = AsyncMock(
        side_effect=InsufficientBalanceError("Баланс API Anthropic меньше 0.")
    )

    await processor.process()

    await db_session.refresh(task)
    assert task.status == "paused", f"Ожидался paused, получено {task.status!r}"
    # Чекпоинт не потерян — resume продолжит с него.
    assert task.progress_data == {"chunks_done": 3}
    assert "баланс" in (task.error_message or "").lower()


async def test_process_generic_error_still_fails(seed_users, db_session):
    """Регрессия: обычная ошибка (не баланс) по-прежнему → failed, не paused."""
    task_id = "d3000000-0000-0000-0000-000000000002"
    task = Task(owner_id=1, 
        id=task_id,
        user_role="user",
        task_type="LIST_FROM_GRAND",
        status="processing",
        estimation_status="not_applicable",
        input_files=[],
        input_file_data=[],
        chat_history=[],
        progress_data={"chunks_done": 1},
    )
    db_session.add(task)
    await db_session.commit()

    processor = TaskProcessor(task_id, db_session)
    processor._handle_list_from_grand = AsyncMock(side_effect=ValueError("boom"))

    await processor.process()

    await db_session.refresh(task)
    assert task.status == "failed"


# ---------------------------------------------------------------------------
# resume-эндпоинт: допускает paused
# ---------------------------------------------------------------------------

async def test_resume_allows_paused_task(async_client, user_token, seed_users, db_session, monkeypatch):
    task_id = "d3000000-0000-0000-0000-000000000003"
    task = Task(owner_id=1, 
        id=task_id,
        user_role="user",
        task_type="LIST_FROM_GRAND",
        status="paused",
        estimation_status="not_applicable",
        input_files=[],
        input_file_data=[],
        chat_history=[],
        progress_data={"chunks_done": 2},
        error_message="Баланс API Anthropic исчерпан.",
    )
    db_session.add(task)
    await db_session.commit()

    # Не запускаем реальную фоновую обработку в тесте.
    monkeypatch.setattr(
        "app.routers.tasks._run_task_in_background", AsyncMock(return_value=None)
    )

    resp = await async_client.post(
        f"/tasks/{task_id}/resume",
        headers={"Authorization": user_token},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"

    await db_session.refresh(task)
    assert task.status == "pending"
    # progress_data (чекпоинт) не очищается при resume.
    assert task.progress_data == {"chunks_done": 2}
