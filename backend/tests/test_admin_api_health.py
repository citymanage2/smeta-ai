"""Тесты админ-эндпоинта GET /admin/api-health и хелперов диагностики паузы.

Зачем: текст паузы фиксированный («баланс API Anthropic исчерпан»), а на сервере
запросы идут через агрегатор (ANTHROPIC_BASE_URL) — понять, чей счёт пуст и дошло
ли пополнение, без пробного вызова нельзя. Эндпоинт делает такой вызов (max_tokens=1)
и отдаёт сырой ответ API + verdict.

План: plans/2026-07-21-resume-and-balance-pause.md, Фаза 9 (диагностика).
"""
import sys
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy import delete

sys.modules.setdefault("fitz", MagicMock())

from app.models.task import Task  # noqa: E402
from tests.helpers.anthropic_api import PROXY_URL, balance_error  # noqa: E402


# ---------------------------------------------------------------------------
# Гард доступа
# ---------------------------------------------------------------------------

async def test_api_health_requires_admin(async_client, user_token, seed_users):
    resp = await async_client.get(
        "/admin/api-health", headers={"Authorization": user_token}
    )
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# verdict по ответу пробного вызова
# ---------------------------------------------------------------------------

def _ping(**over) -> dict:
    base = {
        "ok": True,
        "status_code": 200,
        "error": None,
        "error_code": None,
        "is_balance_error": False,
        "base_url": "https://proxy.example/v1",
        "via_proxy": True,
        "api_key_set": True,
        "proxy_secret_set": True,
        "model": "claude-sonnet-4-6",
    }
    base.update(over)
    return base


async def test_api_health_ok(async_client, admin_token, seed_users, db_session, monkeypatch):
    monkeypatch.setattr(
        "app.services.claude_service.api_ping", AsyncMock(return_value=_ping())
    )
    resp = await async_client.get(
        "/admin/api-health", headers={"Authorization": admin_token}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["verdict"] == "ok"
    assert "paused_tasks" in body
    # секреты не утекают — только флаги
    assert "api_key" not in body
    assert body["api_key_set"] is True


async def test_api_health_no_balance_names_the_proxy(
    async_client, admin_token, seed_users, monkeypatch, claude_api
):
    """Запросы идут через агрегатор, и пустой счёт — его: вердикт «нет денег», и
    ответ говорит, что маршрут — через посредника (пополнять надо его счёт)."""
    from app.config import settings

    monkeypatch.setattr(settings, "ANTHROPIC_BASE_URL", "https://proxy.example")
    claude_api(balance_error(402, "Insufficient funds", url=PROXY_URL))

    resp = await async_client.get(
        "/admin/api-health", headers={"Authorization": admin_token}
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["verdict"] == "no_balance"
    assert body["via_proxy"] is True
    assert body["status_code"] == 402


async def test_api_health_auth_error(async_client, admin_token, seed_users, monkeypatch):
    monkeypatch.setattr(
        "app.services.claude_service.api_ping",
        AsyncMock(return_value=_ping(
            ok=False, status_code=401, error="invalid x-api-key", is_balance_error=False,
        )),
    )
    resp = await async_client.get(
        "/admin/api-health", headers={"Authorization": admin_token}
    )
    body = resp.json()
    assert body["verdict"] == "auth"


async def test_api_health_counts_paused_tasks(
    async_client, admin_token, seed_users, db_session, monkeypatch
):
    monkeypatch.setattr(
        "app.services.claude_service.api_ping", AsyncMock(return_value=_ping())
    )
    task_id = "d9000000-0000-0000-0000-000000000001"
    db_session.add(
        Task(
            owner_id=1, id=task_id, user_role="user", task_type="ESTIMATE_FROM_LIST",
            status="paused", estimation_status="not_applicable",
            input_files=[], input_file_data=[], chat_history=[],
        )
    )
    await db_session.flush()
    try:
        resp = await async_client.get(
            "/admin/api-health", headers={"Authorization": admin_token}
        )
        assert resp.json()["paused_tasks"] >= 1
    finally:
        await db_session.execute(delete(Task).where(Task.id == task_id))
        await db_session.flush()


# ---------------------------------------------------------------------------
# api_ping — сам пробный вызов
# ---------------------------------------------------------------------------

async def test_api_ping_maps_balance_error(monkeypatch):
    from app.services import claude_service as cs
    from tests.helpers.anthropic_api import balance_error

    err = balance_error(400, "credit balance is too low")

    fake_client = MagicMock()
    fake_client.messages.create = AsyncMock(side_effect=err)
    monkeypatch.setattr(cs, "_get_client", lambda: fake_client)

    result = await cs.api_ping()
    assert result["ok"] is False
    assert result["is_balance_error"] is True
    assert "credit balance" in result["error"]


async def test_api_ping_ok(monkeypatch):
    from app.services import claude_service as cs

    fake_client = MagicMock()
    fake_client.messages.create = AsyncMock(return_value=MagicMock())
    monkeypatch.setattr(cs, "_get_client", lambda: fake_client)

    result = await cs.api_ping()
    assert result["ok"] is True
    assert result["status_code"] == 200
    # дешёвый вызов: без web search, max_tokens=1
    kwargs = fake_client.messages.create.await_args.kwargs
    assert kwargs["max_tokens"] == 1
    assert "tools" not in kwargs
