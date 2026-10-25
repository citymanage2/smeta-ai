"""Диагностика должна показывать ресурсы, а не только очередь.

29–30.07.2026 разбор инцидента упёрся в две неизвестные цифры: сколько соединений
разрешает managed-БД (в логе был отказ `Connection reset by peer`) и сколько
памяти съедает обработчик. Обе теперь приходят в `/admin/queue-health` и видны
кнопкой «Проверить сейчас».
"""
import pytest
from sqlalchemy import delete

from app.models.job import Job  # регистрирует таблицу jobs
from app.models.system_event import KIND_WORKER_MEMORY_HIGH, SystemEvent


@pytest.fixture(autouse=True)
async def _clean(db_session):
    await db_session.execute(delete(Job))
    await db_session.execute(delete(SystemEvent))
    await db_session.flush()


async def test_worker_memory_absent_without_events(async_client, admin_token):
    """Жалоб на память не было → null, а не нули (иначе выглядело бы как «0 МБ»)."""
    r = await async_client.get("/admin/queue-health", headers={"Authorization": admin_token})
    assert r.json()["worker_memory"] is None


async def test_worker_memory_takes_latest(async_client, admin_token, db_session):
    """Показываем последнюю жалобу, а не первую: важно текущее состояние."""
    db_session.add(
        SystemEvent(
            kind=KIND_WORKER_MEMORY_HIGH,
            payload={"rss_mb": 1100.0, "threshold_mb": 1024, "concurrency": 4},
        )
    )
    await db_session.flush()
    db_session.add(
        SystemEvent(
            kind=KIND_WORKER_MEMORY_HIGH,
            payload={"rss_mb": 1900.0, "threshold_mb": 1024, "concurrency": 4},
        )
    )
    await db_session.flush()

    r = await async_client.get("/admin/queue-health", headers={"Authorization": admin_token})
    assert r.json()["worker_memory"]["rss_mb"] == 1900.0
