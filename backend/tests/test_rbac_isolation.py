"""Интеграционные тесты изоляции по владельцу и матрицы прав (HTTP-уровень).

Проверяет: списки проектов/задач фильтруются по владельцу, IDOR (чужой ресурс
по id → 404), архив, переназначение владельца, управление аккаунтами (admin_users),
вход именованного админа, backfill legacy-данных.
"""
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.utils.auth import hash_password, create_access_token


def _auth(user_id: int, role: str, username: str = None) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id, role, username)}"}


@pytest_asyncio.fixture
async def rbac_users(db_session):
    """Три аккаунта: pm1, pm2 (project_manager), head (head_of_sales), admin."""
    # Чистим общую in-memory БД от закоммиченных строк других тестов —
    # иначе списки проектов ловят чужие данные (детерминизм под полным прогоном).
    for t in (Task, Project, User):
        await db_session.execute(t.__table__.delete())
    await db_session.commit()

    pm1 = User(username="pm1", role="project_manager", full_name="ПМ Один",
               password_hash=hash_password("pass1"))
    pm2 = User(username="pm2", role="project_manager", full_name="ПМ Два",
               password_hash=hash_password("pass2"))
    head = User(username="head", role="head_of_sales", full_name="Руководитель",
                password_hash=hash_password("pass3"))
    admin = User(username="admin", role="admin", full_name="Админ",
                 password_hash=hash_password("admin123"))
    db_session.add_all([pm1, pm2, head, admin])
    await db_session.flush()

    # Проекты: у pm1 (активный + архивный), у pm2 (активный).
    p_pm1 = Project(name="PM1 active", owner_id=pm1.id, is_archived=False)
    p_pm1_arch = Project(name="PM1 archived", owner_id=pm1.id, is_archived=True)
    p_pm2 = Project(name="PM2 active", owner_id=pm2.id, is_archived=False)
    db_session.add_all([p_pm1, p_pm1_arch, p_pm2])
    await db_session.commit()

    ids = {
        "pm1": pm1.id, "pm2": pm2.id, "head": head.id, "admin": admin.id,
        "p_pm1": str(p_pm1.id), "p_pm1_arch": str(p_pm1_arch.id), "p_pm2": str(p_pm2.id),
    }
    yield ids

    for t in (Task, Project, User):
        await db_session.execute(t.__table__.delete())
    await db_session.commit()


# --- Списки: изоляция + архив ---

@pytest.mark.asyncio
async def test_pm_sees_only_own_active_projects(async_client, rbac_users):
    r = await async_client.get("/projects", headers=_auth(rbac_users["pm1"], "project_manager", "pm1"))
    assert r.status_code == 200
    names = {p["name"] for p in r.json()}
    assert names == {"PM1 active"}  # не видит архив и чужое


@pytest.mark.asyncio
async def test_pm_archived_list(async_client, rbac_users):
    r = await async_client.get("/projects?archived=true", headers=_auth(rbac_users["pm1"], "project_manager", "pm1"))
    assert r.status_code == 200
    names = {p["name"] for p in r.json()}
    assert names == {"PM1 archived"}


@pytest.mark.asyncio
async def test_manager_sees_all_active_projects(async_client, rbac_users):
    r = await async_client.get("/projects", headers=_auth(rbac_users["head"], "head_of_sales", "head"))
    assert r.status_code == 200
    names = {p["name"] for p in r.json()}
    assert names == {"PM1 active", "PM2 active"}


# --- IDOR: чужой проект по id ---

@pytest.mark.asyncio
async def test_pm_cannot_get_foreign_project(async_client, rbac_users):
    r = await async_client.get(f"/projects/{rbac_users['p_pm2']}", headers=_auth(rbac_users["pm1"], "project_manager", "pm1"))
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_pm_can_get_own_project(async_client, rbac_users):
    r = await async_client.get(f"/projects/{rbac_users['p_pm1']}", headers=_auth(rbac_users["pm1"], "project_manager", "pm1"))
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_manager_can_get_foreign_project(async_client, rbac_users):
    r = await async_client.get(f"/projects/{rbac_users['p_pm2']}", headers=_auth(rbac_users["head"], "head_of_sales", "head"))
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_pm_cannot_update_foreign_project(async_client, rbac_users):
    r = await async_client.patch(
        f"/projects/{rbac_users['p_pm2']}",
        json={"name": "hacked"},
        headers=_auth(rbac_users["pm1"], "project_manager", "pm1"),
    )
    assert r.status_code == 404


# --- Владелец при создании ---

@pytest.mark.asyncio
async def test_created_project_owned_by_creator(async_client, rbac_users, db_session):
    r = await async_client.post(
        "/projects", json={"name": "Новый"},
        headers=_auth(rbac_users["pm2"], "project_manager", "pm2"),
    )
    assert r.status_code == 200
    pid = r.json()["id"]
    proj = (await db_session.execute(select(Project).where(Project.id == pid))).scalar_one()
    assert proj.owner_id == rbac_users["pm2"]
    assert proj.is_archived is False


# --- Архивация ---

@pytest.mark.asyncio
async def test_pm_archives_own_project(async_client, rbac_users):
    r = await async_client.patch(
        f"/projects/{rbac_users['p_pm1']}/archive",
        json={"archived": True},
        headers=_auth(rbac_users["pm1"], "project_manager", "pm1"),
    )
    assert r.status_code == 200
    # теперь не в активных
    r2 = await async_client.get("/projects", headers=_auth(rbac_users["pm1"], "project_manager", "pm1"))
    assert all(p["id"] != rbac_users["p_pm1"] for p in r2.json())


@pytest.mark.asyncio
async def test_pm_cannot_archive_foreign(async_client, rbac_users):
    r = await async_client.patch(
        f"/projects/{rbac_users['p_pm2']}/archive",
        json={"archived": True},
        headers=_auth(rbac_users["pm1"], "project_manager", "pm1"),
    )
    assert r.status_code == 404


# --- Переназначение владельца ---

@pytest.mark.asyncio
async def test_manager_reassigns_owner(async_client, rbac_users, db_session):
    r = await async_client.patch(
        f"/projects/{rbac_users['p_pm2']}/owner",
        json={"owner_id": rbac_users["pm1"]},
        headers=_auth(rbac_users["head"], "head_of_sales", "head"),
    )
    assert r.status_code == 200
    proj = (await db_session.execute(select(Project).where(Project.id == rbac_users["p_pm2"]))).scalar_one()
    assert proj.owner_id == rbac_users["pm1"]


@pytest.mark.asyncio
async def test_pm_cannot_reassign_owner(async_client, rbac_users):
    r = await async_client.patch(
        f"/projects/{rbac_users['p_pm1']}/owner",
        json={"owner_id": rbac_users["pm2"]},
        headers=_auth(rbac_users["pm1"], "project_manager", "pm1"),
    )
    assert r.status_code == 403


# --- Управление аккаунтами (admin_users) ---

@pytest.mark.asyncio
async def test_admin_lists_users(async_client, rbac_users):
    r = await async_client.get("/admin/users", headers=_auth(rbac_users["admin"], "admin", "admin"))
    assert r.status_code == 200
    usernames = {u["username"] for u in r.json()}
    assert {"pm1", "pm2", "head", "admin"} <= usernames


@pytest.mark.asyncio
async def test_non_admin_cannot_list_users(async_client, rbac_users):
    r = await async_client.get("/admin/users", headers=_auth(rbac_users["head"], "head_of_sales", "head"))
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_admin_creates_user(async_client, rbac_users, db_session):
    r = await async_client.post(
        "/admin/users",
        json={"username": "newpm", "password": "secret", "role": "project_manager", "full_name": "Новый ПМ"},
        headers=_auth(rbac_users["admin"], "admin", "admin"),
    )
    assert r.status_code == 201
    u = (await db_session.execute(select(User).where(User.username == "newpm"))).scalar_one()
    assert u.role == "project_manager" and u.is_active is True


@pytest.mark.asyncio
async def test_admin_create_duplicate_username_conflict(async_client, rbac_users):
    r = await async_client.post(
        "/admin/users",
        json={"username": "pm1", "password": "secret", "role": "project_manager"},
        headers=_auth(rbac_users["admin"], "admin", "admin"),
    )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_cannot_deactivate_last_admin(async_client, rbac_users):
    # admin в фикстуре — единственный активный админ.
    r = await async_client.patch(
        f"/admin/users/{rbac_users['admin']}",
        json={"is_active": False},
        headers=_auth(rbac_users["admin"], "admin", "admin"),
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_admin_resets_password(async_client, rbac_users, db_session):
    r = await async_client.post(
        f"/admin/users/{rbac_users['pm1']}/reset-password",
        json={"password": "brandnew"},
        headers=_auth(rbac_users["admin"], "admin", "admin"),
    )
    assert r.status_code == 204
    from app.utils.auth import verify_password
    u = (await db_session.execute(select(User).where(User.id == rbac_users["pm1"]))).scalar_one()
    assert verify_password("brandnew", u.password_hash)


# --- Backfill: данные под общими аккаунтами → админ + архив ---

@pytest.mark.asyncio
async def test_backfill_moves_shared_owned_to_admin_archive(db_session, monkeypatch):
    from app import main as main_module
    from app.config import settings
    from tests.conftest import TestSessionLocal

    for t in (Task, Project, User):
        await db_session.execute(t.__table__.delete())
    await db_session.commit()

    # Старый общий аккаунт (username NULL) и данные под ним + «сирота» без владельца.
    shared = User(role="user", is_active=True, password_hash=hash_password("x"))
    db_session.add(shared)
    await db_session.flush()
    shared_id = shared.id
    t_shared = Task(owner_id=shared_id, user_role="user", task_type="LIST_FROM_GRAND",
                    status="completed", input_files=[], input_file_data=[], chat_history=[])
    t_orphan = Task(owner_id=None, user_role="user", task_type="LIST_FROM_GRAND",
                    status="completed", input_files=[], input_file_data=[], chat_history=[])
    p_shared = Project(name="Старый проект", owner_id=shared_id, is_archived=False)
    db_session.add_all([t_shared, t_orphan, p_shared])
    await db_session.commit()
    tid_shared, tid_orphan, pid = str(t_shared.id), str(t_orphan.id), str(p_shared.id)

    monkeypatch.setattr(settings, "ADMIN_USERNAME", "bossadmin")
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", "pw12345")
    monkeypatch.setattr(main_module, "AsyncSessionLocal", TestSessionLocal)
    await main_module._initialize_users()

    admin = (await db_session.execute(select(User).where(User.username == "bossadmin"))).scalar_one()
    # Обе задачи и проект теперь у админа и в архиве.
    for tid in (tid_shared, tid_orphan):
        row = (await db_session.execute(select(Task).where(Task.id == tid))).scalar_one()
        await db_session.refresh(row)
        assert row.owner_id == admin.id and row.is_archived is True
    proj = (await db_session.execute(select(Project).where(Project.id == pid))).scalar_one()
    await db_session.refresh(proj)
    assert proj.owner_id == admin.id and proj.is_archived is True
    # Общий аккаунт деактивирован.
    sh = (await db_session.execute(select(User).where(User.id == shared_id))).scalar_one()
    await db_session.refresh(sh)
    assert sh.is_active is False

    for t in (Task, Project, User):
        await db_session.execute(t.__table__.delete())
    await db_session.commit()


# --- Вход именованного админа ---

@pytest.mark.asyncio
async def test_named_admin_login(async_client, rbac_users):
    r = await async_client.post("/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200
    body = r.json()
    assert body["role"] == "admin" and body["username"] == "admin" and body["access_token"]


# --- IDOR Path B: смета из чужого источника (security-review Finding 1) ---

@pytest.mark.asyncio
async def test_pm_cannot_estimate_from_foreign_source(async_client, rbac_users, db_session):
    # Источник-перечень принадлежит pm2.
    src = Task(
        owner_id=rbac_users["pm2"], user_role="project_manager",
        task_type="LIST_FROM_GRAND", status="completed",
        input_files=[], input_file_data=[], chat_history=[],
    )
    db_session.add(src)
    await db_session.commit()
    # pm1 пытается построить смету из источника pm2 → 404 (не раскрываем существование).
    r = await async_client.post(
        "/tasks",
        data={"task_type": "ESTIMATE_FROM_LIST", "source_task_id": str(src.id)},
        headers=_auth(rbac_users["pm1"], "project_manager", "pm1"),
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_pm_can_estimate_from_own_source(async_client, rbac_users, db_session):
    src = Task(
        owner_id=rbac_users["pm1"], user_role="project_manager",
        task_type="LIST_FROM_GRAND", status="completed",
        input_files=[], input_file_data=[], chat_history=[],
    )
    db_session.add(src)
    await db_session.commit()
    r = await async_client.post(
        "/tasks",
        data={"task_type": "ESTIMATE_FROM_LIST", "source_task_id": str(src.id)},
        headers=_auth(rbac_users["pm1"], "project_manager", "pm1"),
    )
    assert r.status_code in (200, 201)


# --- «Моя корзина» изолирована даже для менеджера (Finding 3) ---

@pytest.mark.asyncio
async def test_archive_loose_task_hides_from_active(async_client, rbac_users, db_session):
    task = Task(
        owner_id=rbac_users["pm1"], user_role="project_manager", task_type="LIST_FROM_GRAND",
        status="completed", input_files=[], input_file_data=[], chat_history=[],
    )
    db_session.add(task)
    await db_session.commit()
    tid = str(task.id)
    hdr = _auth(rbac_users["pm1"], "project_manager", "pm1")

    # Архивируем свою задачу.
    r = await async_client.patch(f"/tasks/{tid}/archive", json={"archived": True}, headers=hdr)
    assert r.status_code == 200 and r.json()["is_archived"] is True

    # В активных «Без проекта» её нет, в архивных — есть.
    active = await async_client.get("/projects/unassigned", headers=hdr)
    assert all(t["id"] != tid for t in active.json())
    archived = await async_client.get("/projects/unassigned?archived=true", headers=hdr)
    assert any(t["id"] == tid for t in archived.json())

    # Возврат из архива.
    r2 = await async_client.patch(f"/tasks/{tid}/archive", json={"archived": False}, headers=hdr)
    assert r2.status_code == 200 and r2.json()["is_archived"] is False


@pytest.mark.asyncio
async def test_pm_cannot_archive_foreign_task(async_client, rbac_users, db_session):
    task = Task(
        owner_id=rbac_users["pm2"], user_role="project_manager", task_type="LIST_FROM_GRAND",
        status="completed", input_files=[], input_file_data=[], chat_history=[],
    )
    db_session.add(task)
    await db_session.commit()
    r = await async_client.patch(
        f"/tasks/{task.id}/archive", json={"archived": True},
        headers=_auth(rbac_users["pm1"], "project_manager", "pm1"),
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_clear_my_trash_only_own_even_for_manager(async_client, rbac_users, db_session):
    now = datetime.now(timezone.utc)
    head_trash = Task(
        owner_id=rbac_users["head"], user_role="head_of_sales", task_type="LIST_FROM_GRAND",
        status="completed", input_files=[], input_file_data=[], chat_history=[], deleted_at=now,
    )
    pm1_trash = Task(
        owner_id=rbac_users["pm1"], user_role="project_manager", task_type="LIST_FROM_GRAND",
        status="completed", input_files=[], input_file_data=[], chat_history=[], deleted_at=now,
    )
    db_session.add_all([head_trash, pm1_trash])
    await db_session.commit()
    pm1_id = pm1_trash.id

    # Менеджер очищает СВОЮ корзину — чужая (pm1) не должна пострадать.
    r = await async_client.delete("/tasks/trash", headers=_auth(rbac_users["head"], "head_of_sales", "head"))
    assert r.status_code == 204
    survived = (await db_session.execute(select(Task).where(Task.id == pm1_id))).scalar_one_or_none()
    assert survived is not None and survived.deleted_at is not None
