"""
Phase 2 — batch-инфраструктура claude_service (Anthropic Message Batches API).

Подменён только клиент Anthropic (`messages.batches`, `messages.create`); журнал
вызовов пишется в тестовую БД.
План: plans/2026-07-21-estimate-processing-modes.md, Phase 2.
"""
from types import SimpleNamespace

import pytest
from sqlalchemy import select

import app.services.claude_service as cs
from app.models.api_call_log import ApiCallLog
from tests.helpers.anthropic_api import claude_message


@pytest.fixture
def batches(monkeypatch):
    """Заглушка SDK-клиента: cs._get_client() → объект с .messages.batches.

    Клиент создаётся лениво (_get_client, с 25.07 — обход геоблока через
    посредника), поэтому подменяем фабрику, а не модульную переменную _client:
    в тестах она None до первого реального вызова.
    """
    batches_ns = SimpleNamespace()
    client = SimpleNamespace(messages=SimpleNamespace(batches=batches_ns))
    monkeypatch.setattr(cs, "_get_client", lambda: client)
    return batches_ns


def test_extract_usage_without_server_tool_use():
    """Вызов без web search: поля server_tool_use в usage нет вовсе."""
    usage = SimpleNamespace(
        input_tokens=10, output_tokens=20,
        cache_read_input_tokens=0, cache_creation_input_tokens=0,
    )
    assert cs._extract_usage(usage) == (10, 20, 0, 0, 0)


# --------------------------------------------------------------------------
# Сборка batch-запроса — паритет с call_claude (модель, tools, кэш system)
# --------------------------------------------------------------------------

def test_build_batch_request_shape():
    req = cs.build_batch_request(
        custom_id="chunk-1",
        messages=[{"role": "user", "content": "hi"}],
        system_prompt="SYS",
        use_web_search=True,
        max_tokens=12345,
    )
    assert req["custom_id"] == "chunk-1"
    params = req["params"]
    assert params["model"] == cs.CLAUDE_MODEL
    assert params["max_tokens"] == 12345
    # web search подключён, и с потолком поисков: без max_uses поиск
    # бесконтрольный — 22% счёта Anthropic на 28.07.2026.
    (tool,) = params["tools"]
    assert tool["name"] == "web_search"
    assert tool["max_uses"] == cs.settings.WEB_SEARCH_MAX_USES >= 1
    # system закэширован
    assert params["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert params["system"][0]["text"] == "SYS"


# --------------------------------------------------------------------------
# Журнал вызовов: batch-запись идемпотентна, обычный вызов пишется всегда.
# resume_from_batch вызывается заново после рестарта поллера — без защиты
# метрика завышалась на каждую пересборку.
# --------------------------------------------------------------------------

def _batch_results(batches, *custom_ids):
    """Пачка, в которой каждый запрос успешно посчитан."""

    async def _results(batch_id):
        async def _stream():
            for cid in custom_ids:
                yield SimpleNamespace(
                    custom_id=cid,
                    result=SimpleNamespace(
                        type="succeeded",
                        message=claude_message({"items": []}, input_tokens=100, output_tokens=50),
                    ),
                )
        return _stream()

    batches.results = _results


async def _logged(db_session, task_id: str) -> list[ApiCallLog]:
    db_session.expire_all()
    return list((await db_session.execute(
        select(ApiCallLog).where(ApiCallLog.task_id == task_id).order_by(ApiCallLog.id)
    )).scalars().all())


async def test_batch_collected_twice_is_logged_once(batches, processor_env, db_session):
    """Повторный сбор той же пачки (рестарт поллера) не дублирует строку журнала."""
    task = await processor_env.task("ESTIMATE_FROM_LIST", status="processing")
    _batch_results(batches, "chunk-0", "chunk-1")

    for _ in range(2):
        await cs.collect_claude_batch("msgbatch_1", task_id=str(task.id), db=db_session)

    rows = await _logged(db_session, str(task.id))
    assert sorted((r.batch_id, r.batch_custom_id) for r in rows) == [
        ("msgbatch_1", "chunk-0"), ("msgbatch_1", "chunk-1"),
    ]


async def test_regular_call_logged_even_if_identical(claude_api, processor_env, db_session):
    """Дедупликация — только для batch-записей: обычные вызовы повторяются
    штатно (ретраи, соседние чанки) и каждый стоит денег."""
    task = await processor_env.task("ESTIMATE_FROM_LIST", status="processing")
    claude_api({"items": []}, repeat=True)

    for _ in range(2):
        await cs.call_claude(
            [{"role": "user", "content": "x"}], task_id=str(task.id), db=db_session,
        )

    rows = await _logged(db_session, str(task.id))
    assert len(rows) == 2
    assert all(r.batch_id is None for r in rows)
