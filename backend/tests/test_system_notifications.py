"""HTTP-контракт ленты системных событий (`GET /notifications/system`).

Контракт (spec: specs/2026-07-28-balance-restored-notification.md):
- AC7: события с id > since_id, по возрастанию, лимит; без авторизации 401;
- AC8: менеджер видит все возобновлённые задачи, ПМ — только свои и общие;
  событие без единой видимой задачи ПМ не показывается, но курсор всё равно
  сдвигается (иначе фронт перезапрашивает его вечно).

План: plans/2026-07-28-balance-restored-notification.md, Фаза 3.
"""
import pytest
import pytest_asyncio

from app.models.system_event import KIND_BALANCE_RESTORED, SystemEvent
from app.models.task import Task
from app.models.user import User
from app.utils.auth import create_access_token, hash_password


def _auth(user_id: int, role: str, username: str = None) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id, role, username)}"}


def _task(task_id: str, owner_id: int, name: str, is_shared: bool = False) -> Task:
    return Task(
        id=task_id,
        user_role="user",
        task_type="LIST_FROM_GRAND",
        status="pending",
        input_files=[],
        input_file_data=[],
        chat_history=[],
        owner_id=owner_id,
        is_shared=is_shared,
        name=name,
    )


@pytest_asyncio.fixture
async def notif_fixture(db_session):
    """Два ПМ, менеджер и событие с тремя задачами: pm1, pm2 и общая."""
    for model in (SystemEvent, Task, User):
        await db_session.execute(model.__table__.delete())
    await db_session.commit()

    pm1 = User(username="n_pm1", role="project_manager", password_hash=hash_password("p"))
    pm2 = User(username="n_pm2", role="project_manager", password_hash=hash_password("p"))
    head = User(username="n_head", role="head_of_sales", password_hash=hash_password("p"))
    db_session.add_all([pm1, pm2, head])
    await db_session.flush()

    t_pm1 = _task("e1000000-0000-0000-0000-000000000001", pm1.id, "Смета ПМ1")
    t_pm2 = _task("e1000000-0000-0000-0000-000000000002", pm2.id, "Смета ПМ2")
    t_shared = _task("e1000000-0000-0000-0000-000000000003", pm2.id, "Общая смета", is_shared=True)
    db_session.add_all([t_pm1, t_pm2, t_shared])

    event = SystemEvent(
        kind=KIND_BALANCE_RESTORED,
        payload={"resumed_task_ids": [t_pm1.id, t_pm2.id, t_shared.id]},
    )
    db_session.add(event)
    await db_session.commit()
    await db_session.refresh(event)

    ids = {
        "pm1": pm1.id, "pm2": pm2.id, "head": head.id,
        "event": event.id,
        "t_pm1": t_pm1.id, "t_pm2": t_pm2.id, "t_shared": t_shared.id,
    }
    yield ids

    for model in (SystemEvent, Task, User):
        await db_session.execute(model.__table__.delete())
    await db_session.commit()


# --- AC7: курсор, порядок, авторизация ---

@pytest.mark.asyncio
async def test_requires_auth(async_client):
    r = await async_client.get("/notifications/system")
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_returns_event_and_cursor(async_client, notif_fixture):
    r = await async_client.get(
        "/notifications/system", headers=_auth(notif_fixture["head"], "head_of_sales", "n_head")
    )
    assert r.status_code == 200
    body = r.json()
    assert body["cursor"] == notif_fixture["event"]
    assert len(body["events"]) == 1
    assert body["events"][0]["kind"] == KIND_BALANCE_RESTORED
    assert body["events"][0]["resumed_count"] == 3


@pytest.mark.asyncio
async def test_since_id_excludes_seen(async_client, notif_fixture):
    r = await async_client.get(
        f"/notifications/system?since_id={notif_fixture['event']}",
        headers=_auth(notif_fixture["head"], "head_of_sales", "n_head"),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["events"] == []
    # Курсор не откатывается назад — иначе показали бы событие повторно.
    assert body["cursor"] == notif_fixture["event"]


@pytest.mark.asyncio
async def test_events_ordered_by_id(async_client, db_session, notif_fixture):
    second = SystemEvent(
        kind=KIND_BALANCE_RESTORED, payload={"resumed_task_ids": [notif_fixture["t_pm1"]]}
    )
    db_session.add(second)
    await db_session.commit()
    await db_session.refresh(second)

    r = await async_client.get(
        "/notifications/system", headers=_auth(notif_fixture["head"], "head_of_sales", "n_head")
    )
    ids = [e["id"] for e in r.json()["events"]]
    assert ids == sorted(ids)
    assert ids[-1] == second.id


# --- AC8: RBAC ---

@pytest.mark.asyncio
async def test_manager_sees_all_tasks(async_client, notif_fixture):
    r = await async_client.get(
        "/notifications/system", headers=_auth(notif_fixture["head"], "head_of_sales", "n_head")
    )
    names = {t["name"] for t in r.json()["events"][0]["tasks"]}
    assert names == {"Смета ПМ1", "Смета ПМ2", "Общая смета"}


@pytest.mark.asyncio
async def test_pm_sees_only_own_and_shared(async_client, notif_fixture):
    r = await async_client.get(
        "/notifications/system", headers=_auth(notif_fixture["pm1"], "project_manager", "n_pm1")
    )
    event = r.json()["events"][0]
    names = {t["name"] for t in event["tasks"]}
    assert names == {"Смета ПМ1", "Общая смета"}, "чужая задача не должна утекать"
    assert event["resumed_count"] == 2


@pytest.mark.asyncio
async def test_event_without_visible_tasks_hidden_but_cursor_moves(
    async_client, db_session, notif_fixture
):
    """ПМ, которому не видна ни одна задача события, уведомления не получает —
    но курсор двигается, иначе фронт запрашивал бы это событие бесконечно."""
    for model in (SystemEvent,):
        await db_session.execute(model.__table__.delete())
    lonely = SystemEvent(
        kind=KIND_BALANCE_RESTORED, payload={"resumed_task_ids": [notif_fixture["t_pm2"]]}
    )
    db_session.add(lonely)
    await db_session.commit()
    await db_session.refresh(lonely)

    r = await async_client.get(
        "/notifications/system", headers=_auth(notif_fixture["pm1"], "project_manager", "n_pm1")
    )
    body = r.json()
    assert body["events"] == []
    assert body["cursor"] == lonely.id
