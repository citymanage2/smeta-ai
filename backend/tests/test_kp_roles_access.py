"""Роли отдела производства работ и запрет по умолчанию (запрос КП, фаза 1).

Снабжение (`supply_manager`) и работа с подрядчиками (`contractor_manager`)
видят только запросы КП своей роли. Всё остальное API закрыто зависимостью
`forbid_production_roles`, которая висит на каждом `include_router`, кроме
белого списка. Тест перебирает **все** маршруты приложения: новый роутер, про
который забыли, автоматически оказывается закрытым — а если его включили без
зависимости, этот тест упадёт.

План: plans/2026-09-14-zapros-kp.md, фаза 1.
"""
import re

import pytest
import pytest_asyncio
from fastapi.routing import APIRoute
from sqlalchemy import select

from app.models.task import Task
from app.models.user import User
from app.utils import permissions as perm
from app.utils.auth import create_access_token, hash_password

FORBIDDEN_DETAIL = "Раздел недоступен отделу производства работ"

# Маршруты вне роутеров: служебные и SPA. SPA отдаёт только index.html, данных
# в нём нет; /docs и /openapi.json — описание API, не данные.
NON_ROUTER_PATHS = {
    "/",
    "/health",
    "/{full_path:path}",
    "/docs",
    "/docs/oauth2-redirect",
    "/openapi.json",
    "/redoc",
}

PRODUCTION = [perm.ROLE_SUPPLY, perm.ROLE_CONTRACTOR]


def _bearer(user_id: int, role: str) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id, role, f'u{user_id}')}"}


def _fill_path(path: str) -> str:
    """Подставить значения в параметры пути. Тип не важен: зависимости роутера
    выполняются раньше валидации параметров."""
    return re.sub(r"\{[^}]+\}", "1", path)


# --- Чистая логика ролей -----------------------------------------------------

def test_production_roles_are_not_project_manager():
    """`normalize_role` превращал неизвестную роль в ПМ — новая роль молча
    получила бы полный доступ ко всем проектам."""
    assert perm.normalize_role("supply_manager") == perm.ROLE_SUPPLY
    assert perm.normalize_role("contractor_manager") == perm.ROLE_CONTRACTOR
    assert perm.normalize_role("supply_manager") != perm.ROLE_PM
    # Прежнее поведение для legacy и мусора не меняется.
    assert perm.normalize_role("user") == perm.ROLE_PM
    assert perm.normalize_role("garbage") == perm.ROLE_PM
    assert perm.normalize_role(None) == perm.ROLE_PM


def test_role_fits_user_column():
    """Колонка `users.role` — String(32): миграция не нужна."""
    assert all(len(r) <= User.__table__.c.role.type.length for r in perm.ASSIGNABLE_ROLES)


# --- Перебор всех маршрутов --------------------------------------------------

def _router_routes(app):
    routes = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            assert route.path in NON_ROUTER_PATHS, (
                f"Неизвестный маршрут вне роутеров: {route.path}"
            )
            continue
        if route.path in NON_ROUTER_PATHS:
            continue
        routes.append(route)
    return routes


@pytest.mark.asyncio
@pytest.mark.parametrize("role", PRODUCTION)
async def test_every_route_outside_whitelist_is_forbidden(async_client, test_app, role):
    headers = _bearer(424242, role)
    checked = 0
    leaks = []
    for route in _router_routes(test_app):
        if perm.is_production_allowed_path(route.path):
            continue
        url = _fill_path(route.path)
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            # Пустое тело: кривой JSON дал бы 422 раньше зависимостей.
            resp = await async_client.request(method, url, headers=headers)
            checked += 1
            if resp.status_code != 403 or resp.json().get("detail") != FORBIDDEN_DETAIL:
                leaks.append(f"{method} {route.path} → {resp.status_code}")
    assert not leaks, "Маршруты открыты отделу производства:\n" + "\n".join(leaks)
    # Защита от пустого перебора: маршрутов в приложении больше сотни.
    assert checked > 100


def test_whitelist_is_only_auth_and_kp():
    assert perm.is_production_allowed_path("/auth/login")
    assert perm.is_production_allowed_path("/kp-requests")
    assert perm.is_production_allowed_path("/kp-requests/{request_id}")
    assert not perm.is_production_allowed_path("/kp-requestsX")
    assert not perm.is_production_allowed_path("/projects")
    assert not perm.is_production_allowed_path("/authors")
    assert not perm.is_production_allowed_path("/api/cards")


@pytest.mark.asyncio
@pytest.mark.parametrize("role", PRODUCTION)
async def test_login_open_for_production(async_client, db_session, role):
    user = User(username=f"login-{role}", role=role, password_hash=hash_password("pass1"))
    db_session.add(user)
    await db_session.commit()
    try:
        resp = await async_client.post(
            "/auth/login", json={"username": f"login-{role}", "password": "pass1"},
        )
        assert resp.status_code == 200
        assert resp.json()["role"] == role
    finally:
        await db_session.delete(user)
        await db_session.commit()


# --- Роль из БД или из токена ------------------------------------------------

@pytest_asyncio.fixture
async def pm_user(db_session):
    user = User(username="kp-roles-pm", role="project_manager", password_hash=hash_password("x1234"))
    db_session.add(user)
    await db_session.commit()
    yield user
    await db_session.execute(User.__table__.delete().where(User.id == user.id))
    await db_session.commit()


@pytest.mark.asyncio
async def test_pm_token_but_role_changed_in_db_is_forbidden(async_client, db_session, pm_user):
    """Роль сменили залогиненному: токен ещё говорит «ПМ», база — «снабжение».
    Повышение до производства закрывает доступ сразу, без перелогина."""
    headers = _bearer(pm_user.id, "project_manager")
    await db_session.execute(
        User.__table__.update().where(User.id == pm_user.id).values(role="supply_manager")
    )
    await db_session.commit()
    resp = await async_client.get("/projects", headers=headers)
    assert resp.status_code == 403
    assert resp.json()["detail"] == FORBIDDEN_DETAIL


@pytest.mark.asyncio
async def test_production_token_but_db_role_pm_still_forbidden(async_client, pm_user):
    """Обратное направление — после перелогина: безопасная сторона."""
    resp = await async_client.get("/projects", headers=_bearer(pm_user.id, "contractor_manager"))
    assert resp.status_code == 403
    assert resp.json()["detail"] == FORBIDDEN_DETAIL


@pytest.mark.asyncio
async def test_production_token_in_query_is_forbidden(async_client, seed_users):
    from tests.conftest import SEEDED_TASK_ID
    token = create_access_token(1, "supply_manager")
    resp = await async_client.get(f"/tasks/{SEEDED_TASK_ID}/input-file/0?token={token}")
    assert resp.status_code == 403
    assert resp.json()["detail"] == FORBIDDEN_DETAIL


@pytest.mark.asyncio
async def test_download_by_query_token_for_pm_still_works(async_client, seed_users):
    from tests.conftest import SEEDED_TASK_ID
    token = create_access_token(1, "project_manager")
    resp = await async_client.get(f"/tasks/{SEEDED_TASK_ID}/input-file/0?token={token}")
    assert resp.status_code == 200
    assert resp.content == b"test"


@pytest.mark.asyncio
async def test_download_by_query_token_db_role_production_forbidden(async_client, seed_users, db_session):
    """Роль в БД проверяется и для токена из `?token=`."""
    from tests.conftest import SEEDED_TASK_ID
    await db_session.execute(
        User.__table__.update().where(User.id == 1).values(role="contractor_manager")
    )
    await db_session.commit()
    token = create_access_token(1, "project_manager")
    resp = await async_client.get(f"/tasks/{SEEDED_TASK_ID}/input-file/0?token={token}")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_calculator_without_token_unchanged(async_client):
    resp = await async_client.post("/calculator/room", json={"length": 4, "width": 3, "height": 2.7})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_no_token_still_401_from_endpoint(async_client):
    """Нет токена — зависимость пропускает, аутентификацию решает ручка."""
    resp = await async_client.get("/projects")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_invalid_token_still_401_from_endpoint(async_client):
    resp = await async_client.get("/projects", headers={"Authorization": "Bearer garbage"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_legacy_token_without_numeric_sub_not_broken(async_client, seed_users):
    """Legacy-токен без числового sub: в базу не ходим, решает роль токена."""
    from jose import jwt
    from app.config import settings
    token = jwt.encode(
        {"sub": "project_manager", "role": "project_manager"},
        settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM,
    )
    resp = await async_client.get("/projects", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


# --- Сотрудники --------------------------------------------------------------

@pytest_asyncio.fixture
async def admin_user(db_session):
    user = User(username="kp-roles-admin", role="admin", password_hash=hash_password("x1234"))
    db_session.add(user)
    await db_session.commit()
    yield user
    await db_session.execute(
        User.__table__.delete().where(User.username.like("kp-roles-%"))
    )
    await db_session.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("role", PRODUCTION)
async def test_admin_creates_employee_with_production_role(async_client, admin_user, role):
    resp = await async_client.post(
        "/admin/users",
        headers=_bearer(admin_user.id, "admin"),
        json={"username": f"kp-roles-new-{role}", "password": "pass1", "role": role},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["role"] == role


@pytest.mark.asyncio
async def test_admin_changes_role_to_production(async_client, admin_user, db_session):
    emp = User(username="kp-roles-emp", role="project_manager", password_hash=hash_password("x1234"))
    db_session.add(emp)
    await db_session.commit()
    resp = await async_client.patch(
        f"/admin/users/{emp.id}",
        headers=_bearer(admin_user.id, "admin"),
        json={"role": "contractor_manager"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["role"] == "contractor_manager"


@pytest.mark.asyncio
async def test_production_employees_not_offered_as_owners(async_client, admin_user, db_session):
    """Владелец проекта/задачи — ключ очереди и подпись «чьё это»; сотрудник
    производства проекты не видит, предлагать его в владельцы нельзя."""
    db_session.add_all([
        User(username="kp-roles-supply", role="supply_manager", password_hash=hash_password("x1234")),
        User(username="kp-roles-pm2", role="project_manager", password_hash=hash_password("x1234")),
    ])
    await db_session.commit()
    resp = await async_client.get("/admin/users/assignable", headers=_bearer(admin_user.id, "admin"))
    assert resp.status_code == 200
    names = {u["display_name"] for u in resp.json()}
    assert "kp-roles-pm2" in names
    assert "kp-roles-supply" not in names


def test_is_admin_and_is_manager():
    assert perm.is_admin("admin")
    assert not perm.is_admin("head_of_sales")
    assert perm.is_manager("admin")
    assert perm.is_manager("head_of_sales")
    assert not perm.is_manager("project_manager")
    assert not perm.is_manager("user")  # legacy → pm
