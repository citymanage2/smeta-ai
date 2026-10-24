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

import anthropic
import pytest

sys.modules.setdefault("fitz", MagicMock())

from app.services.claude_service import (  # noqa: E402
    call_claude,
    InsufficientBalanceError,
)
from app.services.task_processor import TaskProcessor  # noqa: E402
from app.models.task import Task  # noqa: E402
from tests.helpers.anthropic_api import api_error, balance_error  # noqa: E402


# ---------------------------------------------------------------------------
# claude_service: типизированная ошибка баланса
# ---------------------------------------------------------------------------

async def test_credit_balance_4xx_raises_insufficient_balance(claude_api, api_sleeps):
    claude_api(balance_error())

    with pytest.raises(InsufficientBalanceError):
        await call_claude([{"role": "user", "content": "hi"}])


async def test_non_balance_4xx_not_wrapped(claude_api, api_sleeps):
    """Прочие 4xx (не про баланс) НЕ превращаются в InsufficientBalanceError."""
    claude_api(api_error(400, "bad request"))

    with pytest.raises(anthropic.APIStatusError):
        await call_claude([{"role": "user", "content": "hi"}])


# ---------------------------------------------------------------------------
# Чанковые retry-обёртки: баланс пробрасывается сразу, без ретраев
# ---------------------------------------------------------------------------

async def test_chunk_retry_reraises_balance_immediately(db_session, claude_api, api_sleeps):
    """Пустой счёт — один запрос к API и сразу пауза: повтор денег не вернёт."""
    ai = claude_api(balance_error())
    p = TaskProcessor("tid-bal", db=db_session)

    with pytest.raises(InsufficientBalanceError):
        await p._call_claude_json_with_retry(
            [{"role": "user", "content": "x"}], system_prompt="s",
            chunk_retry_delays=(0.0, 0.0, 0.0),
        )

    assert len(ai.calls) == 1
    assert api_sleeps == []


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
