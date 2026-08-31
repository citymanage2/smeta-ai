"""Тесты админ-эндпоинта GET /admin/api-health и хелперов диагностики паузы.

Зачем: текст паузы фиксированный («баланс API Anthropic исчерпан»), а на сервере
запросы идут через агрегатор (ANTHROPIC_BASE_URL) — понять, чей счёт пуст и дошло
ли пополнение, без пробного вызова нельзя. Эндпоинт делает такой вызов (max_tokens=1)
и отдаёт сырой ответ API + verdict.

План: plans/2026-07-21-resume-and-balance-pause.md, Фаза 9 (диагностика).
"""
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import delete

sys.modules.setdefault("fitz", MagicMock())

import app.routers.admin as admin_router  # noqa: E402
from app.models.task import Task  # noqa: E402
from app.services.claude_service import InsufficientBalanceError  # noqa: E402
from app.services.task_processor import _balance_error_detail  # noqa: E402


# ---------------------------------------------------------------------------
# _balance_error_detail — сырой ответ API в шаге прогресса
# ---------------------------------------------------------------------------

def test_balance_detail_includes_status_and_message():
    err = InsufficientBalanceError(
        "нет денег", status_code=402, api_message="Your credit balance is too low"
    )
    detail = _balance_error_detail(err)
    assert "402" in detail
    assert "credit balance" in detail


def test_balance_detail_empty_without_api_data():
    # Старый способ создания (без деталей) — хвост не добавляем.
    assert _balance_error_detail(InsufficientBalanceError("нет денег")) == ""
    assert _balance_error_detail(RuntimeError("boom")) == ""


def test_balance_detail_truncates_long_message():
    err = InsufficientBalanceError("x", status_code=402, api_message="y" * 500)
    assert len(_balance_error_detail(err)) < 260


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
    async_client, admin_token, seed_users, monkeypatch
):
    """Если base_url задан, «баланс исчерпан» относится к агрегатору — так и пишем."""
    monkeypatch.setattr(
        "app.services.claude_service.api_ping",
        AsyncMock(return_value=_ping(
            ok=False, status_code=402, error="Your credit balance is too low",
            is_balance_error=True,
        )),
    )
    resp = await async_client.get(
        "/admin/api-health", headers={"Authorization": admin_token}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["verdict"] == "no_balance"
    assert "агрегатора" in body["hint"]
    assert "402" in body["hint"]


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
    import anthropic
    import httpx2

    from app.services import claude_service as cs

    body = {"error": {"type": "invalid_request_error", "message": "credit balance is too low"}}
    raw = httpx2.Response(
        status_code=400, headers={}, content=b"{}",
        request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"),
    )
    err = anthropic.APIStatusError("credit balance", response=raw, body=body)

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
