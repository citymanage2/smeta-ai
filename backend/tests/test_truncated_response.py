"""Обрезанный ответ (stop_reason=max_tokens) — самый дорогой путь до 28.07.2026.

Было: ValueError бросался ДО логирования, а _call_claude_json_with_retry ретраил
его как временную ошибку — три полных вызова по 32k output (~$1.44), все
оплаченные, все обречённые (промпт не менялся) и ни один не попал в метрику.

Стало: ResponseTruncatedError, usage логируется до падения, ретрая нет,
чанк дробится пополам.

План: plans/2026-07-28-снижение-числа-вызовов-claude.md, Фаза 1.
"""
import re
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

import app.services.claude_service as cs
import app.worker as worker
from app.models.api_call_log import ApiCallLog
from app.models.job import Job
from app.services import estimate_store
from app.services.claude_service import ResponseTruncatedError
from app.services.task_processor import TaskProcessor
from tests.helpers.anthropic_api import claude_message, prompt_text


def _response(stop_reason: str, output_tokens: int = 32000):
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(text='{"items": []}')],
        usage=SimpleNamespace(
            input_tokens=1000,
            output_tokens=output_tokens,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
            server_tool_use=SimpleNamespace(web_search_requests=4),
        ),
    )


def _patch_client(monkeypatch, response) -> dict:
    """Клиент-заглушка; возвращает счётчик обращений к messages.create."""
    calls = {"n": 0}

    async def fake_create(**kwargs):
        calls["n"] += 1
        return response

    client = SimpleNamespace(messages=SimpleNamespace(create=fake_create))
    monkeypatch.setattr(cs, "_get_client", lambda: client)
    return calls


async def test_truncated_response_raises_typed_error(monkeypatch):
    _patch_client(monkeypatch, _response("max_tokens"))

    with pytest.raises(ResponseTruncatedError):
        await cs.call_claude([{"role": "user", "content": "x"}])


async def test_truncated_response_is_still_logged(processor_env, claude_api, db_session):
    """Оборванный ответ оплачен — токены должны попасть в метрику."""
    task_id = str((await processor_env.task("ESTIMATE_FROM_LIST", status="processing")).id)
    claude_api(claude_message(
        {"items": []}, stop_reason="max_tokens",
        input_tokens=1000, output_tokens=32000, web_search_requests=4,
    ))

    with pytest.raises(ResponseTruncatedError):
        await cs.call_claude(
            [{"role": "user", "content": "x"}], task_id=task_id, db=db_session,
        )

    db_session.expire_all()
    (row,) = (await db_session.execute(
        select(ApiCallLog).where(ApiCallLog.task_id == task_id)
    )).scalars().all()
    assert row.output_tokens == 32000
    assert row.web_search_requests == 4
    assert row.cost_usd > 0


async def test_truncated_response_not_retried_by_chunk_retry(monkeypatch):
    """Ретрай тем же промптом снова упрётся в потолок — повторов быть не должно."""
    calls = _patch_client(monkeypatch, _response("max_tokens"))
    p = TaskProcessor("tid-trunc", db=MagicMock())

    with pytest.raises(ResponseTruncatedError):
        await p._call_claude_json_with_retry(
            [{"role": "user", "content": "x"}],
            system_prompt="SYS",
            chunk_retry_delays=(0.0, 0.0, 0.0),
        )

    assert calls["n"] == 1, f"ожидался один вызов, сделано {calls['n']}"


# --------------------------------------------------------------------------
# Дробление порции пополам — на кнопке «Исправить пустые цены», где весь путь
# (эндпоинт → job воркера → сбор батчей → вызов → применение) идёт целиком.
# --------------------------------------------------------------------------

async def test_truncated_batch_is_split_in_half_and_priced(
    processor_env, claude_api, async_client, user_token, db_session,
):
    """Батч из 5 позиций не влез в ответ → две половины, все цены проставлены."""
    task = await processor_env.task("ESTIMATE_FROM_LIST", status="completed")
    task_id = str(task.id)
    await estimate_store.write_items(db_session, task, [
        {"type": "Работа", "name": f"Работа {i}", "unit": "м3", "quantity": 1, "work_price": None}
        for i in range(5)
    ])
    sizes: list[int] = []

    def answer(kwargs):
        ids = [int(x) for x in re.findall(r'"id":\s*(\d+)', prompt_text(kwargs))]
        sizes.append(len(ids))
        if len(sizes) == 1:
            return claude_message({"items": []}, stop_reason="max_tokens")
        return {"items": [{"id": i, "type": "Работа", "work_price": 100 + i} for i in ids]}

    ai = claude_api(answer, repeat=True)

    response = await async_client.post(
        f"/tasks/{task_id}/estimate-items/fix-empty-prices",
        headers={"Authorization": user_token},
    )
    assert response.status_code == 200
    assert response.json() == {"empty_count": 5, "status": "started"}
    db_session.expire_all()
    jobs = (await db_session.execute(select(Job).where(Job.kind == "task.fix_prices"))).scalars().all()
    (job,) = [j for j in jobs if j.payload.get("task_id") == task_id]
    await worker.run_job(job)

    # Один обрезанный вызов на 5 позиций → две половины вместо трёх повторов.
    assert len(ai.calls) == 3
    assert sizes == [5, 2, 3]
    task = await processor_env.reload(task)
    assert task.status == "completed"
    items = await processor_env.estimate_items(task)
    assert [it["work_price"] for it in items] == [100, 101, 102, 103, 104]
