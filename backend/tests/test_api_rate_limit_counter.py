"""Ответы 429 от API видны в диагностике админки.

04.08.2026: разбирали идею «несколько ключей API = несколько задач параллельно».
Лимиты Anthropic считаются на организацию, а не на ключ, поэтому второй ключ в том
же аккаунте ничего не добавляет. Остался вопрос про посредника (`ANTHROPIC_BASE_URL`)
— у него лимиты свои. Ответить было нечем: 429 уходил только в лог контейнера,
который пользователю недоступен. Теперь каждый 429 — строка в `system_events`, а
`/admin/queue-health` показывает, сколько их за час и за сутки.

План: plans/2026-08-04-schetchik-429-v-adminke.md, Фаза 1.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select

from app.models.job import Job  # регистрирует таблицу jobs
from app.models.workflow_card import WorkflowCard  # noqa: F401 — на неё ссылается document_locks
from app.models.system_event import KIND_API_RATE_LIMITED, SystemEvent
from app.services import claude_service
from tests.helpers.anthropic_api import (
    PROXY_URL, balance_error, claude_message, rate_limit_error,
)


@pytest.fixture(autouse=True)
async def _clean(db_session):
    await db_session.execute(delete(Job))
    await db_session.execute(delete(SystemEvent))
    await db_session.flush()


def _event(created_at: datetime, **payload) -> SystemEvent:
    base = {"wait_s": 60.0, "attempt": 1, "rate_limit_count": 1, "via_proxy": True}
    base.update(payload)
    return SystemEvent(kind=KIND_API_RATE_LIMITED, payload=base, created_at=created_at)


# --- запись события -------------------------------------------------------


async def test_rate_limit_is_recorded(async_client, admin_token, claude_api, api_sleeps):
    """Один 429 — одна строка в диагностике: сколько раз и сколько ждали.

    Событие пишется своей сессией (как и журнал вызовов API); `async_client`
    направляет её в тестовую БД.
    """
    ai = claude_api(rate_limit_error(retry_after=30), claude_message("ok"))

    assert await claude_service.call_claude([{"role": "user", "content": "привет"}]) == "ok"

    assert len(ai.calls) == 2
    # retry-after 30 с меньше минимального шага бэкоффа — ждём 60.
    assert api_sleeps == [60]
    r = await async_client.get("/admin/queue-health", headers={"Authorization": admin_token})
    info = r.json()["api_rate_limits"]
    assert info["hits_1h"] == 1
    assert info["max_wait_s_24h"] == 60


async def test_recording_failure_never_raises(monkeypatch, claude_api, api_sleeps):
    """Диагностика не важнее работы: упавшая запись не должна ронять вызов Claude."""
    import app.database

    def _boom(*_args, **_kwargs):
        raise RuntimeError("БД недоступна")

    monkeypatch.setattr(app.database, "AsyncSessionLocal", _boom)
    claude_api(rate_limit_error(retry_after=30), claude_message("ok"))

    assert await claude_service.call_claude([{"role": "user", "content": "привет"}]) == "ok"


async def test_balance_error_is_not_counted(db_session, test_app, claude_api, api_sleeps):
    """«Нет денег» приходит от посредника под видом 429 — это не лимит запросов.

    Если бы такие ответы попадали в счётчик, он показывал бы упор в лимит там, где
    на самом деле кончились деньги, и увёл бы разбор в сторону.
    """
    ai = claude_api(balance_error(429, url=PROXY_URL))

    with pytest.raises(claude_service.InsufficientBalanceError):
        await claude_service.call_claude([{"role": "user", "content": "привет"}])

    assert len(ai.calls) == 1
    assert api_sleeps == []
    db_session.expire_all()
    count = (
        await db_session.execute(
            select(SystemEvent).where(SystemEvent.kind == KIND_API_RATE_LIMITED)
        )
    ).scalars().all()
    assert count == []


# --- выдача в диагностику -------------------------------------------------


async def test_absent_without_events(async_client, admin_token):
    """Событий не было — null, а не нули: «0 за сутки» и «нет данных» это разное."""
    r = await async_client.get("/admin/queue-health", headers={"Authorization": admin_token})
    assert r.status_code == 200
    assert r.json()["api_rate_limits"] is None


async def test_counts_are_split_by_window(async_client, admin_token, db_session):
    """Час и сутки считаются раздельно: важно, идёт ли это прямо сейчас."""
    now = datetime.now(timezone.utc)
    db_session.add_all([
        _event(now - timedelta(minutes=5), wait_s=60.0),
        _event(now - timedelta(minutes=30), wait_s=120.0),
        _event(now - timedelta(hours=5), wait_s=900.0),
        _event(now - timedelta(days=2), wait_s=900.0),  # за пределами суток
    ])
    await db_session.flush()

    body = (
        await async_client.get("/admin/queue-health", headers={"Authorization": admin_token})
    ).json()

    info = body["api_rate_limits"]
    assert info["hits_1h"] == 2
    assert info["hits_24h"] == 3
    assert info["max_wait_s_24h"] == 900.0
    assert info["last_age_s"] < 3600
    assert info["via_proxy"] is True

