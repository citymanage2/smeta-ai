"""Authentication endpoint tests — вход только по персональному логину+паролю."""
import pytest
import pytest_asyncio

from app.models.user import User
from app.utils.auth import hash_password


@pytest_asyncio.fixture
async def login_user(db_session):
    """Активный аккаунт (логин+пароль) и один деактивированный."""
    active = User(username="ivanov", role="project_manager", full_name="Иванов",
                  is_active=True, password_hash=hash_password("secret123"))
    disabled = User(username="petrov", role="project_manager", full_name="Петров",
                    is_active=False, password_hash=hash_password("secret123"))
    db_session.add_all([active, disabled])
    await db_session.commit()
    yield
    await db_session.execute(User.__table__.delete())
    await db_session.commit()


async def test_login_valid(async_client, login_user):
    """Верные логин+пароль → 200 с токеном и ролью."""
    response = await async_client.post(
        "/auth/login", json={"username": "ivanov", "password": "secret123"}
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data.get("access_token"), str) and len(data["access_token"]) > 0
    assert data["role"] == "project_manager"
    assert data["username"] == "ivanov"


async def test_login_wrong_password(async_client, login_user):
    response = await async_client.post(
        "/auth/login", json={"username": "ivanov", "password": "wrong"}
    )
    assert response.status_code == 401
    assert "Неверный" in response.json()["detail"]


async def test_login_unknown_user(async_client, login_user):
    response = await async_client.post(
        "/auth/login", json={"username": "nobody", "password": "secret123"}
    )
    assert response.status_code == 401


async def test_login_password_only_rejected(async_client, login_user):
    """Вход по общему паролю (без логина) удалён → 400."""
    response = await async_client.post("/auth/login", json={"password": "secret123"})
    assert response.status_code == 400
    assert "логин" in response.json()["detail"].lower()


async def test_login_empty(async_client, login_user):
    response = await async_client.post("/auth/login", json={"username": "", "password": ""})
    assert response.status_code == 400


async def test_login_deactivated_user(async_client, login_user):
    """Деактивированный аккаунт войти не может."""
    response = await async_client.post(
        "/auth/login", json={"username": "petrov", "password": "secret123"}
    )
    assert response.status_code == 401
