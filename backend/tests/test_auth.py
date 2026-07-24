"""Authentication endpoint tests."""
import pytest


async def test_login_valid_user(async_client, seed_users):
    """Valid user password returns 200 with token and role=user."""
    response = await async_client.post("/auth/login", json={"password": "user123"})
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data.get("access_token"), str)
    assert len(data["access_token"]) > 0
    assert data["role"] == "user"
    assert data["expires_in"] == 86400


async def test_login_valid_admin(async_client, seed_users):
    """Valid admin password returns 200 with role=admin."""
    response = await async_client.post("/auth/login", json={"password": "admin123"})
    assert response.status_code == 200
    data = response.json()
    assert data["role"] == "admin"
    assert isinstance(data.get("access_token"), str)


async def test_login_invalid_password(async_client, seed_users):
    """Wrong password returns 401 with Russian error detail."""
    response = await async_client.post("/auth/login", json={"password": "wrongpassword"})
    assert response.status_code == 401
    assert "Неверный" in response.json()["detail"]


async def test_login_empty_password(async_client, seed_users):
    """Empty password returns 400 with Russian error detail."""
    response = await async_client.post("/auth/login", json={"password": ""})
    assert response.status_code == 400
    assert "Пароль не может быть пустым" in response.json()["detail"]
