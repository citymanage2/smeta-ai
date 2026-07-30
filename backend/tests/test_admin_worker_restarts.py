"""Перезапуски обработчика видны в диагностике — это улика смерти контейнера.

30.07.2026: три возобновлённые задачи повисли разом, потому что контейнер
обработчика получал OOM-kill и поднимался заново. Увидеть это было негде: при
убийстве процесса жалоба на память не пишется, а лог Timeweb пользователю
недоступен. Теперь каждый старт обработчика — событие в `system_events`, а
`/admin/queue-health` показывает, сколько их за час.

План: plans/2026-07-30-parallelnaya-obrabotka-umiraet.md, Фаза 4.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete

from app.models.job import Job  # регистрирует таблицу jobs
from app.models.system_event import KIND_WORKER_STARTED, SystemEvent


@pytest.fixture(autouse=True)
async def _clean(db_session):
    await db_session.execute(delete(Job))
    await db_session.execute(delete(SystemEvent))
    await db_session.flush()


def _start_event(**payload) -> SystemEvent:
    base = {
        "worker_id": "box-1:7",
        "slots": 2,
        "configured_concurrency": 4,
        "requeued": 0,
        "rss_mb": 780.0,
        "usage_mb": 800.0,
        "limit_mb": 2048.0,
        "ratio": 0.39,
    }
    base.update(payload)
    return SystemEvent(kind=KIND_WORKER_STARTED, payload=base)


async def test_absent_without_events(async_client, admin_token):
    """Событий нет — null, а не нули: «0 стартов» звучало бы как поломка."""
    r = await async_client.get("/admin/queue-health", headers={"Authorization": admin_token})
    assert r.status_code == 200
    assert r.json()["worker_restarts"] is None


async def test_single_start_is_reported_calmly(async_client, admin_token, db_session):
    """Один старт — норма (деплой): цифры видны, тревоги в подсказке нет."""
    db_session.add(_start_event())
    await db_session.flush()

    body = (
        await async_client.get("/admin/queue-health", headers={"Authorization": admin_token})
    ).json()

    info = body["worker_restarts"]
    assert info["starts_1h"] == 1
    assert info["slots"] == 2
    assert info["limit_mb"] == 2048.0
    assert info["rss_mb"] == 780.0
    assert info["last_age_s"] is not None
    assert "перезапускался" not in body["hint"]


async def test_repeated_starts_flagged_in_hint(async_client, admin_token, db_session):
    """Три старта за час — контейнер умирает: диагноз прямо в подсказке."""
    for _ in range(3):
        db_session.add(_start_event())
    await db_session.flush()

    body = (
        await async_client.get("/admin/queue-health", headers={"Authorization": admin_token})
    ).json()

    assert body["worker_restarts"]["starts_1h"] == 3
    assert "перезапускался 3" in body["hint"]
    assert "памяти" in body["hint"]


async def test_old_starts_not_counted_but_last_shown(async_client, admin_token, db_session):
    """Старты сутками ранее в счёт часа не идут, но цифры последнего показываем."""
    old = _start_event(slots=1)
    old.created_at = datetime.now(timezone.utc) - timedelta(hours=5)
    db_session.add(old)
    await db_session.flush()

    info = (
        await async_client.get("/admin/queue-health", headers={"Authorization": admin_token})
    ).json()["worker_restarts"]

    assert info["starts_1h"] == 0
    assert info["slots"] == 1
    assert info["last_age_s"] > 3600


async def test_takes_latest_start(async_client, admin_token, db_session):
    """Показываем последний старт: важно текущее состояние, а не первое."""
    db_session.add(_start_event(slots=4, limit_mb=8192.0))
    await db_session.flush()
    db_session.add(_start_event(slots=1, limit_mb=1024.0, requeued=3))
    await db_session.flush()

    info = (
        await async_client.get("/admin/queue-health", headers={"Authorization": admin_token})
    ).json()["worker_restarts"]

    assert info["slots"] == 1
    assert info["limit_mb"] == 1024.0
    assert info["requeued"] == 3


async def test_missing_memory_numbers_degrade_to_null(async_client, admin_token, db_session):
    """Платформа без cgroup (локально) — цифр нет, но эндпоинт не падает."""
    db_session.add(
        SystemEvent(kind=KIND_WORKER_STARTED, payload={"worker_id": "mac:1", "slots": 4})
    )
    await db_session.flush()

    info = (
        await async_client.get("/admin/queue-health", headers={"Authorization": admin_token})
    ).json()["worker_restarts"]

    assert info["limit_mb"] is None
    assert info["rss_mb"] is None
    assert info["slots"] == 4
