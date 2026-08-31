"""Клиент официального отчёта о тратах Anthropic (`cost_report`).

Главная ловушка эндпоинта — единица измерения: `amount` приходит СТРОКОЙ В
ЦЕНТАХ. `"123.45"` при `currency: "USD"` означает $1.23. Прочитать это как
доллары — ошибиться в сто раз, причём в сторону «денег почти не осталось».
Поэтому перевод закреплён тестом с точным числом.

Второй тест — про пустой день: Anthropic возвращает бакет с пустым `results`, и
это не «нет данных», а честный ноль. Пропустить такой день нельзя — иначе день
без трат остался бы несинхронизированным навсегда.

План: plans/2026-09-01-ostatok-deneg-na-api.md, Фаза 3.
"""
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from app.services import anthropic_admin


def _bucket(day: str, amounts: list[str]) -> dict:
    """Бакет одного дня в формате ответа Anthropic (суммы — в центах)."""
    return {
        "starting_at": f"{day}T00:00:00Z",
        "ending_at": f"{day}T23:59:59Z",
        "results": [
            {"amount": a, "currency": "USD", "cost_type": "tokens"} for a in amounts
        ],
    }


class TestAmountUnits:
    """Центы из ответа переводятся в доллары на границе клиента."""

    @pytest.mark.asyncio
    async def test_cents_to_dollars(self):
        payload = {
            "data": [_bucket("2026-08-30", ["123.45"])],
            "has_more": False,
            "next_page": None,
        }
        with patch.object(
            anthropic_admin, "_request", AsyncMock(return_value=payload)
        ), patch.object(anthropic_admin.settings, "ANTHROPIC_ADMIN_KEY", "sk-ant-admin01-x"):
            days = await anthropic_admin.fetch_cost_days(
                date(2026, 8, 30), date(2026, 8, 31)
            )
        assert days == {date(2026, 8, 30): Decimal("1.2345")}

    @pytest.mark.asyncio
    async def test_positions_of_one_day_are_summed(self):
        """Строки дня (вход, выход, кеш, web-поиск) складываются в одну сумму."""
        payload = {
            "data": [_bucket("2026-08-30", ["1000.00", "250.50", "9.50"])],
            "has_more": False,
            "next_page": None,
        }
        with patch.object(
            anthropic_admin, "_request", AsyncMock(return_value=payload)
        ), patch.object(anthropic_admin.settings, "ANTHROPIC_ADMIN_KEY", "sk-ant-admin01-x"):
            days = await anthropic_admin.fetch_cost_days(
                date(2026, 8, 30), date(2026, 8, 31)
            )
        # (1000.00 + 250.50 + 9.50) центов = 1260 центов = $12.60
        assert days == {date(2026, 8, 30): Decimal("12.60")}


class TestEmptyDay:
    @pytest.mark.asyncio
    async def test_day_without_costs_is_zero_not_missing(self):
        payload = {
            "data": [_bucket("2026-08-29", []), _bucket("2026-08-30", ["500.00"])],
            "has_more": False,
            "next_page": None,
        }
        with patch.object(
            anthropic_admin, "_request", AsyncMock(return_value=payload)
        ), patch.object(anthropic_admin.settings, "ANTHROPIC_ADMIN_KEY", "sk-ant-admin01-x"):
            days = await anthropic_admin.fetch_cost_days(
                date(2026, 8, 29), date(2026, 8, 31)
            )
        assert days[date(2026, 8, 29)] == Decimal("0")
        assert days[date(2026, 8, 30)] == Decimal("5.00")


class TestPagination:
    @pytest.mark.asyncio
    async def test_follows_next_page(self):
        first = {
            "data": [_bucket("2026-08-29", ["100.00"])],
            "has_more": True,
            "next_page": "page_abc",
        }
        second = {
            "data": [_bucket("2026-08-30", ["200.00"])],
            "has_more": False,
            "next_page": None,
        }
        request = AsyncMock(side_effect=[first, second])
        with patch.object(anthropic_admin, "_request", request), patch.object(
            anthropic_admin.settings, "ANTHROPIC_ADMIN_KEY", "sk-ant-admin01-x"
        ):
            days = await anthropic_admin.fetch_cost_days(
                date(2026, 8, 29), date(2026, 8, 31)
            )
        assert days == {
            date(2026, 8, 29): Decimal("1.00"),
            date(2026, 8, 30): Decimal("2.00"),
        }
        # Второй запрос ушёл с курсором предыдущего ответа.
        assert request.await_args_list[1].kwargs["params"]["page"] == "page_abc"


class TestNoKey:
    @pytest.mark.asyncio
    async def test_returns_none_without_admin_key(self):
        """Без админ-ключа — None, а не исключение: фича обязана работать без него."""
        with patch.object(anthropic_admin.settings, "ANTHROPIC_ADMIN_KEY", ""):
            assert (
                await anthropic_admin.fetch_cost_days(date(2026, 8, 30), date(2026, 8, 31))
                is None
            )


class TestErrors:
    @pytest.mark.asyncio
    async def test_http_error_propagates(self):
        """401/403 не глотаем: вызывающий должен показать, что сверка сломана."""
        with patch.object(
            anthropic_admin,
            "_request",
            AsyncMock(side_effect=anthropic_admin.AdminApiError("401 unauthorized")),
        ), patch.object(anthropic_admin.settings, "ANTHROPIC_ADMIN_KEY", "sk-ant-admin01-x"):
            with pytest.raises(anthropic_admin.AdminApiError):
                await anthropic_admin.fetch_cost_days(
                    date(2026, 8, 30), date(2026, 8, 31)
                )
