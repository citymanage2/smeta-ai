"""Фаза 4 ETA: прогноз доезжает до очереди, карточки задачи и канбана."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.models.project import Project
from app.models.task import Task
from app.models.workflow_card import WorkflowCard
from app.utils.volume_probe import UNIT_ITEMS

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def clean_tasks(db_session):
    await db_session.execute(text("DELETE FROM tasks"))
    await db_session.commit()
    yield
    await db_session.execute(text("DELETE FROM tasks"))
    await db_session.commit()


async def _add_task(db, **kw) -> Task:
    fields = dict(
        id=str(uuid.uuid4()),
        user_role="admin",
        owner_id=2,
        task_type="ESTIMATE_FROM_LIST",
        status="pending",
        input_files=[],
        input_file_data=[],
        chat_history=[],
        volume_units=200,
        volume_kind=UNIT_ITEMS,
    )
    fields.update(kw)
    task = Task(**fields)
    db.add(task)
    await db.commit()
    return task


async def test_dashboard_queue_carries_eta(async_client, db_session, admin_token):
    task = await _add_task(db_session)

    resp = await async_client.get("/dashboard/stats", headers={"Authorization": admin_token})
    assert resp.status_code == 200

    row = next(t for t in resp.json()["active_queue"] if t["id"] == task.id)
    eta = row["eta"]
    assert eta is not None
    assert eta["ready_in_s"] > 0
    assert eta["units"] == 200
    assert eta["unit_kind"] == UNIT_ITEMS
    assert eta["ready_at"]


async def test_queue_position_delays_the_start(async_client, db_session, admin_token):
    """Задачи сверх числа слотов ждут — и это видно в прогнозе старта."""
    from app.config import settings

    earlier = datetime.now(timezone.utc) - timedelta(hours=1)
    for i in range(settings.WORKER_CONCURRENCY):
        await _add_task(db_session, status="processing", started_at=earlier,
                        created_at=earlier - timedelta(minutes=i))
    waiting = await _add_task(db_session)

    resp = await async_client.get("/dashboard/stats", headers={"Authorization": admin_token})
    row = next(t for t in resp.json()["active_queue"] if t["id"] == waiting.id)

    assert row["eta"]["starts_in_s"] > 0


async def test_task_status_carries_eta_only_while_active(async_client, db_session, admin_token):
    task = await _add_task(db_session)

    resp = await async_client.get(
        f"/tasks/{task.id}/status", headers={"Authorization": admin_token}
    )
    assert resp.status_code == 200
    assert resp.json()["eta"] is not None

    task.status = "completed"
    await db_session.commit()

    resp = await async_client.get(
        f"/tasks/{task.id}/status", headers={"Authorization": admin_token}
    )
    assert resp.json()["eta"] is None


async def test_kanban_card_carries_eta(async_client, db_session, admin_token):
    pid = str(uuid.uuid4())
    db_session.add(Project(id=pid, name="ETA проект", owner_id=2))
    await db_session.commit()

    task = await _add_task(db_session, project_id=pid)
    db_session.add(WorkflowCard(
        id=str(uuid.uuid4()), project_id=pid, name="Карточка",
        stage="estimate", estimate_task_id=task.id,
    ))
    await db_session.commit()

    resp = await async_client.get(
        f"/api/projects/{pid}/workflow-cards", headers={"Authorization": admin_token}
    )
    assert resp.status_code == 200
    card = resp.json()[0]
    assert card["estimate_task"]["eta"]["ready_in_s"] > 0


async def test_kanban_etag_survives_a_second_poll(async_client, db_session, admin_token):
    """Прогноз округлён до минуты — иначе он ломал бы 304 на каждом опросе доски."""
    pid = str(uuid.uuid4())
    db_session.add(Project(id=pid, name="ETag + ETA", owner_id=2))
    await db_session.commit()

    task = await _add_task(db_session, project_id=pid)
    db_session.add(WorkflowCard(
        id=str(uuid.uuid4()), project_id=pid, name="Карточка",
        stage="estimate", estimate_task_id=task.id,
    ))
    await db_session.commit()

    url = f"/api/projects/{pid}/workflow-cards"
    first = await async_client.get(url, headers={"Authorization": admin_token})
    etag = first.headers["etag"]

    second = await async_client.get(
        url, headers={"Authorization": admin_token, "If-None-Match": etag}
    )
    assert second.status_code == 304
