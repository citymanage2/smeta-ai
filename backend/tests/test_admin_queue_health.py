"""Тесты админ-эндпоинта GET /admin/queue-health.

Проверяют: гард админа, счётчики по статусам, возрасты queued/running,
детекцию stale running и verdict (idle/ok/busy/stalled).

План: plans/2026-07-28-admin-queue-health.md.
"""
from datetime import datetime, timezone, timedelta

import pytest

from app.models.job import Job  # noqa: F401 — регистрирует таблицу jobs в Base.metadata
from app.config import settings


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _add_job(db, *, status, created_ago_s=0, claimed_ago_s=None):
    """Вставить job с относительными возрастами (сек назад)."""
    job = Job(
        kind="task.process",
        payload={"task_id": "t"},
        status=status,
        created_at=_now() - timedelta(seconds=created_ago_s),
        claimed_at=(_now() - timedelta(seconds=claimed_ago_s)) if claimed_ago_s is not None else None,
    )
    db.add(job)
    # flush, НЕ commit: эндпоинт работает в той же сессии (override_get_db) и
    # увидит незакоммиченные строки, а откат db_session изолирует тесты
    # (commit пережил бы rollback и «протёк» бы в следующий тест).
    await db.flush()
    return job


# ---------------------------------------------------------------------------
# Гард доступа
# ---------------------------------------------------------------------------

async def test_queue_health_requires_admin(async_client, user_token):
    r = await async_client.get("/admin/queue-health", headers={"Authorization": user_token})
    assert r.status_code == 403


async def test_queue_health_no_auth(async_client):
    r = await async_client.get("/admin/queue-health")
    assert r.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Содержимое
# ---------------------------------------------------------------------------

async def test_queue_health_empty_is_idle(async_client, admin_token):
    r = await async_client.get("/admin/queue-health", headers={"Authorization": admin_token})
    assert r.status_code == 200
    data = r.json()
    assert data["counts"] == {"queued": 0, "running": 0, "done": 0, "failed": 0}
    assert data["queued"]["oldest_age_s"] is None
    assert data["running"]["count"] == 0
    assert data["running"]["oldest_claimed_age_s"] is None
    assert data["running"]["stale_count"] == 0
    assert data["verdict"] == "idle"
    assert data["visibility_timeout_s"] == settings.JOB_VISIBILITY_TIMEOUT_S


async def test_queue_health_counts(async_client, admin_token, db_session):
    await _add_job(db_session, status="done", created_ago_s=10)
    await _add_job(db_session, status="done", created_ago_s=9)
    await _add_job(db_session, status="failed", created_ago_s=8)
    await _add_job(db_session, status="running", created_ago_s=5, claimed_ago_s=1)

    r = await async_client.get("/admin/queue-health", headers={"Authorization": admin_token})
    data = r.json()
    assert data["counts"] == {"queued": 0, "running": 1, "done": 2, "failed": 1}
    # queued==0, running>0 → "ok"
    assert data["verdict"] == "ok"


async def test_queue_health_stalled_when_queued_and_no_live_worker(async_client, admin_token, db_session):
    # queued-job старше порога, нет running → worker не разбирает очередь.
    await _add_job(db_session, status="queued", created_ago_s=300)
    r = await async_client.get("/admin/queue-health", headers={"Authorization": admin_token})
    data = r.json()
    assert data["counts"]["queued"] == 1
    assert data["queued"]["oldest_age_s"] >= 120
    assert data["verdict"] == "stalled"
    assert "worker" in data["hint"].lower()


async def test_queue_health_busy_when_queued_but_running_fresh(async_client, admin_token, db_session):
    # Бэклог есть, но worker жив (свежий running) → не алярм, а "busy".
    await _add_job(db_session, status="queued", created_ago_s=300)
    await _add_job(db_session, status="running", created_ago_s=310, claimed_ago_s=2)
    r = await async_client.get("/admin/queue-health", headers={"Authorization": admin_token})
    data = r.json()
    assert data["verdict"] == "busy"
    assert data["running"]["stale_count"] == 0


async def test_queue_health_stale_running_counted(async_client, admin_token, db_session):
    # running с claimed_at старше visibility timeout → кандидат на reclaim.
    old = settings.JOB_VISIBILITY_TIMEOUT_S + 100
    await _add_job(db_session, status="running", created_ago_s=old + 10, claimed_ago_s=old)
    await _add_job(db_session, status="queued", created_ago_s=300)
    r = await async_client.get("/admin/queue-health", headers={"Authorization": admin_token})
    data = r.json()
    assert data["running"]["stale_count"] == 1
    assert data["running"]["oldest_claimed_age_s"] >= settings.JOB_VISIBILITY_TIMEOUT_S
    # queued старше порога + единственный running протух → нет живого worker → stalled.
    assert data["verdict"] == "stalled"
