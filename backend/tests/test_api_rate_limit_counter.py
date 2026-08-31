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
from typing import Optional

import anthropic
import httpx2
import pytest
from sqlalchemy import delete, select

from app.models.job import Job  # регистрирует таблицу jobs
from app.models.workflow_card import WorkflowCard  # noqa: F401 — на неё ссылается document_locks
from app.models.system_event import KIND_API_RATE_LIMITED, SystemEvent
from app.services import claude_service


@pytest.fixture(autouse=True)
async def _clean(db_session):
    await db_session.execute(delete(Job))
    await db_session.execute(delete(SystemEvent))
    await db_session.flush()


def _rate_limit_error(retry_after: Optional[str] = "30") -> anthropic.RateLimitError:
    """Настоящий RateLimitError SDK — чтобы ловился именно тот except, что в коде."""
    headers = {"retry-after": retry_after} if retry_after is not None else {}
    response = httpx2.Response(
        429,
        headers=headers,
        request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"),
        json={"error": {"type": "rate_limit_error", "message": "rate limit"}},
    )
    return anthropic.RateLimitError("rate limit", response=response, body=None)


def _event(created_at: datetime, **payload) -> SystemEvent:
    base = {"wait_s": 60.0, "attempt": 1, "rate_limit_count": 1, "via_proxy": True}
    base.update(payload)
    return SystemEvent(kind=KIND_API_RATE_LIMITED, payload=base, created_at=created_at)


# --- запись события -------------------------------------------------------


async def test_rate_limit_is_recorded(db_session, test_app):
    """429 пишет строку с цифрами, по которым видно масштаб ожидания.

    `test_app` здесь не ради HTTP: эта фикстура подменяет `AsyncSessionLocal` на
    тестовую, а событие пишется в своей сессии (как и лог вызовов API).
    """
    await claude_service._record_rate_limit(
        _rate_limit_error(), wait_s=60.0, attempt=2, rate_limit_count=1
    )

    row = (
        await db_session.execute(
            select(SystemEvent).where(SystemEvent.kind == KIND_API_RATE_LIMITED)
        )
    ).scalars().one()
    assert row.payload["wait_s"] == 60.0
    assert row.payload["attempt"] == 2
    assert row.payload["retry_after_s"] == 30.0
    assert "via_proxy" in row.payload


async def test_recording_failure_never_raises(monkeypatch):
    """Диагностика не важнее работы: упавшая запись не должна ронять вызов Claude."""
    import app.database

    def _boom(*_args, **_kwargs):
        raise RuntimeError("БД недоступна")

    monkeypatch.setattr(app.database, "AsyncSessionLocal", _boom)

    # Ровно то, что проверяем: исключение не выходит наружу.
    await claude_service._record_rate_limit(
        _rate_limit_error(), wait_s=60.0, attempt=1, rate_limit_count=1
    )


async def test_balance_error_is_not_counted(db_session, test_app, monkeypatch):
    """«Нет денег» приходит от посредника под видом 429 — это не лимит запросов.

    Если бы такие ответы попадали в счётчик, он показывал бы упор в лимит там, где
    на самом деле кончились деньги, и увёл бы разбор в сторону.
    """
    balance_error = _rate_limit_error()
    monkeypatch.setattr(
        claude_service,
        "_raise_if_insufficient_balance",
        lambda e: (_ for _ in ()).throw(claude_service.InsufficientBalanceError("нет средств")),
    )

    async def _fake_create(**_kwargs):
        raise balance_error

    monkeypatch.setattr(
        claude_service, "_get_client", lambda: type("C", (), {
            "messages": type("M", (), {"create": staticmethod(_fake_create)})()
        })()
    )

    with pytest.raises(claude_service.InsufficientBalanceError):
        await claude_service.call_claude([{"role": "user", "content": "привет"}])

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


async def test_recent_hits_add_hint(async_client, admin_token, db_session):
    """Свежие 429 должны быть названы в подсказке — иначе цифру не заметят."""
    db_session.add(_event(datetime.now(timezone.utc) - timedelta(minutes=2)))
    await db_session.flush()

    body = (
        await async_client.get("/admin/queue-health", headers={"Authorization": admin_token})
    ).json()

    assert "429" in body["hint"] or "лимит" in body["hint"].lower()


async def test_old_hits_do_not_alarm(async_client, admin_token, db_session):
    """Вчерашние 429 — история, а не текущая проблема: подсказку не трогаем."""
    db_session.add(_event(datetime.now(timezone.utc) - timedelta(hours=10)))
    await db_session.flush()

    body = (
        await async_client.get("/admin/queue-health", headers={"Authorization": admin_token})
    ).json()

    assert body["api_rate_limits"]["hits_1h"] == 0
    assert body["api_rate_limits"]["hits_24h"] == 1
    assert "429" not in body["hint"]
