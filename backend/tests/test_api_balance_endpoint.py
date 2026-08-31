"""HTTP-контракт остатка денег на Claude API.

Проверяется то, что видно снаружи: права, валидация суммы и даты, и что ответ
меняется сразу после отметки — без ожидания фоновой сверки с Anthropic.

План: plans/2026-09-01-ostatok-deneg-na-api.md, Фаза 5.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import delete

from app.models.api_balance import ApiBalanceMark, ApiCostDay
from app.models.api_call_log import ApiCallLog


@pytest.fixture(autouse=True)
async def _clean(db_session):
    for model in (ApiCallLog, ApiCostDay, ApiBalanceMark):
        await db_session.execute(delete(model))
    await db_session.commit()
    yield


class TestPermissions:
    @pytest.mark.asyncio
    async def test_regular_user_forbidden(self, async_client, user_token):
        response = await async_client.get("/api-balance", headers={"Authorization": user_token})
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_regular_user_cannot_mark(self, async_client, user_token):
        response = await async_client.post(
            "/api-balance/marks",
            json={"balance_usd": 100},
            headers={"Authorization": user_token},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_manager_allowed(self, async_client, admin_token):
        response = await async_client.get("/api-balance", headers={"Authorization": admin_token})
        assert response.status_code == 200


class TestEmptyState:
    @pytest.mark.asyncio
    async def test_without_mark_remaining_is_null(self, async_client, admin_token):
        response = await async_client.get("/api-balance", headers={"Authorization": admin_token})
        body = response.json()
        assert body["remaining_usd"] is None
        assert body["level"] == "unknown"
        assert body["marks"] == []


class TestMarkLifecycle:
    @pytest.mark.asyncio
    async def test_mark_immediately_changes_balance(self, async_client, admin_token, db_session):
        # Трата «прямо сейчас» — она обязана попасть в остаток без синхронизации.
        db_session.add(
            ApiCallLog(
                model="claude-sonnet-5",
                input_tokens=0,
                output_tokens=0,
                cache_read_tokens=0,
                cache_creation_tokens=0,
                cost_usd=Decimal("12.00"),
                called_at=datetime.now(timezone.utc),
            )
        )
        await db_session.commit()

        response = await async_client.post(
            "/api-balance/marks",
            json={"balance_usd": 500, "note": "Из Console"},
            headers={"Authorization": admin_token},
        )
        assert response.status_code == 201
        body = response.json()
        assert body["mark_usd"] == 500.0
        assert body["live_usd"] == pytest.approx(12.0)
        assert body["remaining_usd"] == pytest.approx(488.0)
        assert len(body["marks"]) == 1

    @pytest.mark.asyncio
    async def test_delete_mark_returns_to_unknown(self, async_client, admin_token):
        created = await async_client.post(
            "/api-balance/marks",
            json={"balance_usd": 300},
            headers={"Authorization": admin_token},
        )
        mark_id = created.json()["marks"][0]["id"]

        response = await async_client.delete(
            f"/api-balance/marks/{mark_id}", headers={"Authorization": admin_token}
        )
        assert response.status_code == 200
        assert response.json()["remaining_usd"] is None

    @pytest.mark.asyncio
    async def test_latest_mark_wins(self, async_client, admin_token):
        today = datetime.now(timezone.utc).date()
        await async_client.post(
            "/api-balance/marks",
            json={"balance_usd": 100, "measured_on": str(today - timedelta(days=5))},
            headers={"Authorization": admin_token},
        )
        response = await async_client.post(
            "/api-balance/marks",
            json={"balance_usd": 900, "measured_on": str(today)},
            headers={"Authorization": admin_token},
        )
        assert response.json()["mark_usd"] == 900.0


class TestValidation:
    @pytest.mark.asyncio
    async def test_future_date_rejected(self, async_client, admin_token):
        tomorrow = datetime.now(timezone.utc).date() + timedelta(days=1)
        response = await async_client.post(
            "/api-balance/marks",
            json={"balance_usd": 100, "measured_on": str(tomorrow)},
            headers={"Authorization": admin_token},
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_zero_and_negative_rejected(self, async_client, admin_token):
        for amount in (0, -5):
            response = await async_client.post(
                "/api-balance/marks",
                json={"balance_usd": amount},
                headers={"Authorization": admin_token},
            )
            assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_absurd_amount_rejected(self, async_client, admin_token):
        """Лишний ноль в сумме иначе врал бы до следующей отметки."""
        response = await async_client.post(
            "/api-balance/marks",
            json={"balance_usd": 5_000_000},
            headers={"Authorization": admin_token},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_delete_missing_mark_is_404(self, async_client, admin_token):
        response = await async_client.delete(
            "/api-balance/marks/999999", headers={"Authorization": admin_token}
        )
        assert response.status_code == 404


class TestSyncEndpoint:
    @pytest.mark.asyncio
    async def test_sync_survives_anthropic_failure(self, async_client, admin_token, monkeypatch):
        """Отказ Anthropic не роняет страницу — остаток считается по своему журналу."""
        from app.services import balance_service
        from app.services.anthropic_admin import AdminApiError

        async def boom(*args, **kwargs):
            raise AdminApiError("401 unauthorized")

        monkeypatch.setattr(balance_service, "sync_cost_days", boom)
        response = await async_client.post(
            "/api-balance/sync", headers={"Authorization": admin_token}
        )
        assert response.status_code == 200


class TestSyncDiagnostics:
    """Кнопка сверки обязана сказать, ЧЕМ ответил Anthropic.

    Без текста ответа «не сработало» выглядит одинаково при неподходящем ключе,
    закрытом на прокси пути и личной организации — а чинятся они по-разному.
    """

    @pytest.mark.asyncio
    async def test_error_text_reaches_response(self, async_client, admin_token, monkeypatch):
        from app.services import balance_service
        from app.services.anthropic_admin import AdminApiError

        async def boom(*args, **kwargs):
            raise AdminApiError("Отчёт о тратах: HTTP 401 invalid x-api-key")

        monkeypatch.setattr(balance_service, "sync_cost_days", boom)
        response = await async_client.post(
            "/api-balance/sync", headers={"Authorization": admin_token}
        )
        assert response.status_code == 200
        assert "401" in response.json()["sync_error"]

    @pytest.mark.asyncio
    async def test_success_has_no_error(self, async_client, admin_token, monkeypatch):
        from app.services import balance_service

        async def ok(*args, **kwargs):
            return 3

        monkeypatch.setattr(balance_service, "sync_cost_days", ok)
        response = await async_client.post(
            "/api-balance/sync", headers={"Authorization": admin_token}
        )
        assert response.json()["sync_error"] is None
