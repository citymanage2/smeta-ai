"""Расчёт остатка денег на Claude API.

Главное, что здесь проверяется, — граница между двумя источниками трат.
Официальные данные Anthropic (`api_cost_days`) закрывают дни до сегодняшнего,
собственный журнал вызовов (`api_call_log`) — сегодняшний день. Ошибка в границе
не даёт «небольшую неточность»: она либо вычитает одну и ту же смету дважды,
либо теряет её совсем.

Второе — поведение без официальной сверки: админ-ключа может не быть, и остаток
обязан считаться по своему журналу, а не исчезать.

План: plans/2026-09-01-ostatok-deneg-na-api.md, Фаза 4.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.models.api_balance import ApiBalanceMark, ApiCostDay
from app.models.api_call_log import ApiCallLog
from app.services import balance_service


@pytest.fixture(autouse=True)
async def _clean(db_session):
    """Таблицы общие на весь прогон, а хелперы коммитят — чистим перед тестом.

    Иначе траты одного теста утекают в остаток другого, и падение выглядит как
    ошибка расчёта, хотя дело в чужих данных.
    """
    for model in (ApiCallLog, ApiCostDay, ApiBalanceMark):
        await db_session.execute(delete(model))
    await db_session.commit()
    yield


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc)


async def _mark(db, balance: str, measured_on: date) -> None:
    db.add(ApiBalanceMark(balance_usd=Decimal(balance), measured_on=measured_on))
    await db.commit()


async def _official(db, day: date, amount: str) -> None:
    db.add(ApiCostDay(day=day, amount_usd=Decimal(amount)))
    await db.commit()


async def _call(db, called_at: datetime, cost: str) -> None:
    db.add(
        ApiCallLog(
            model="claude-sonnet-5",
            input_tokens=0,
            output_tokens=0,
            cache_read_tokens=0,
            cache_creation_tokens=0,
            cost_usd=Decimal(cost),
            called_at=called_at,
        )
    )
    await db.commit()


class TestSourceBoundary:
    """Закрытые дни — официально, сегодня — из своего журнала. Без пересечений."""

    @pytest.mark.asyncio
    async def test_today_from_own_log_closed_days_from_official(self, db_session):
        now = _utc(datetime(2026, 9, 3, 15, 0))
        today = now.date()
        await _mark(db_session, "500.00", today - timedelta(days=2))
        # Закрытые дни: официальные суммы Anthropic.
        await _official(db_session, today - timedelta(days=2), "30.00")
        await _official(db_session, today - timedelta(days=1), "20.00")
        # Те же дни есть и в своём журнале — они НЕ должны сложиться с официальными.
        await _call(db_session, now - timedelta(days=2), "31.00")
        await _call(db_session, now - timedelta(days=1), "19.00")
        # Сегодняшняя трата: только из своего журнала.
        await _call(db_session, now - timedelta(hours=1), "7.50")

        snap = await balance_service.compute_balance(db_session, now=now)

        assert snap.official_usd == pytest.approx(50.0)
        assert snap.live_usd == pytest.approx(7.5)
        assert snap.spent_usd == pytest.approx(57.5)
        assert snap.remaining_usd == pytest.approx(442.5)

    @pytest.mark.asyncio
    async def test_spending_before_mark_is_ignored(self, db_session):
        """Траты до отметки уже учтены в самой отметке — вычитать их нельзя."""
        now = _utc(datetime(2026, 9, 3, 12, 0))
        today = now.date()
        await _mark(db_session, "100.00", today - timedelta(days=1))
        await _call(db_session, now - timedelta(days=10), "999.00")
        await _official(db_session, today - timedelta(days=5), "888.00")
        await _official(db_session, today - timedelta(days=1), "10.00")

        snap = await balance_service.compute_balance(db_session, now=now)

        assert snap.spent_usd == pytest.approx(10.0)
        assert snap.remaining_usd == pytest.approx(90.0)


class TestWithoutOfficialData:
    """Без админ-ключа и без синхронизации остаток считается по своему журналу."""

    @pytest.mark.asyncio
    async def test_falls_back_to_own_log(self, db_session):
        now = _utc(datetime(2026, 9, 3, 10, 0))
        today = now.date()
        await _mark(db_session, "200.00", today - timedelta(days=2))
        await _call(db_session, now - timedelta(days=2), "12.00")
        await _call(db_session, now - timedelta(days=1), "8.00")
        await _call(db_session, now - timedelta(minutes=30), "5.00")

        snap = await balance_service.compute_balance(db_session, now=now)

        assert snap.spent_usd == pytest.approx(25.0)
        assert snap.remaining_usd == pytest.approx(175.0)
        assert snap.official_through is None

    @pytest.mark.asyncio
    async def test_partial_official_data_no_gap_no_overlap(self, db_session):
        """Часть дней официальная, часть — нет: каждый день считается ровно раз."""
        now = _utc(datetime(2026, 9, 5, 9, 0))
        today = now.date()
        await _mark(db_session, "300.00", today - timedelta(days=4))
        # Официально известны только два последних закрытых дня.
        await _official(db_session, today - timedelta(days=2), "10.00")
        await _official(db_session, today - timedelta(days=1), "20.00")
        # Свой журнал знает про все дни.
        await _call(db_session, now - timedelta(days=4), "5.00")
        await _call(db_session, now - timedelta(days=3), "6.00")
        await _call(db_session, now - timedelta(days=2), "11.00")
        await _call(db_session, now - timedelta(days=1), "21.00")
        await _call(db_session, now - timedelta(hours=2), "3.00")

        snap = await balance_service.compute_balance(db_session, now=now)

        # 5 + 6 (свои, до официального периода) + 10 + 20 (официальные) + 3 (сегодня)
        assert snap.spent_usd == pytest.approx(44.0)
        assert snap.official_through == today - timedelta(days=1)


class TestNoMark:
    @pytest.mark.asyncio
    async def test_without_mark_remaining_is_unknown(self, db_session):
        """Точки отсчёта нет — остаток неизвестен, а не ноль."""
        now = _utc(datetime(2026, 9, 3, 10, 0))
        await _call(db_session, now - timedelta(hours=1), "4.00")

        snap = await balance_service.compute_balance(db_session, now=now)

        assert snap.remaining_usd is None
        assert snap.level == "unknown"
        assert snap.spent_usd == pytest.approx(0.0)


class TestNegativeBalance:
    @pytest.mark.asyncio
    async def test_overspent_shown_as_is(self, db_session):
        """Потрачено больше отметки — показываем минус, а не ноль.

        Это единственный видимый признак «счёт пополнили и не отметили».
        Обнулить его — скрыть от человека, что цифре нельзя верить.
        """
        now = _utc(datetime(2026, 9, 3, 10, 0))
        today = now.date()
        await _mark(db_session, "10.00", today)
        await _call(db_session, now - timedelta(hours=1), "25.00")

        snap = await balance_service.compute_balance(db_session, now=now)

        assert snap.remaining_usd == pytest.approx(-15.0)
        assert snap.level == "alarm"


class TestForecast:
    @pytest.mark.asyncio
    async def test_days_left_from_weekly_pace(self, db_session):
        """«Хватит на N дней» — по собственному темпу за последнюю неделю."""
        now = _utc(datetime(2026, 9, 10, 12, 0))
        today = now.date()
        await _mark(db_session, "700.00", today)
        # Неделя ровного расхода по $10 в день (7 дней до сегодняшнего).
        for i in range(1, 8):
            await _call(db_session, now - timedelta(days=i), "10.00")

        snap = await balance_service.compute_balance(db_session, now=now)

        assert snap.avg_daily_usd == pytest.approx(10.0)
        assert snap.days_left == pytest.approx(70.0)
        assert snap.level == "ok"

    @pytest.mark.asyncio
    async def test_low_balance_raises_alarm(self, db_session):
        now = _utc(datetime(2026, 9, 10, 12, 0))
        today = now.date()
        await _mark(db_session, "8.00", today)
        for i in range(1, 8):
            await _call(db_session, now - timedelta(days=i), "10.00")

        snap = await balance_service.compute_balance(db_session, now=now)

        # Меньше суток по текущему темпу.
        assert snap.days_left == pytest.approx(0.8)
        assert snap.level == "alarm"

    @pytest.mark.asyncio
    async def test_no_spending_means_no_forecast(self, db_session):
        """Нулевой темп — прогноз не выдумываем (делить на ноль нечем)."""
        now = _utc(datetime(2026, 9, 10, 12, 0))
        await _mark(db_session, "100.00", now.date())

        snap = await balance_service.compute_balance(db_session, now=now)

        assert snap.days_left is None
        assert snap.level == "ok"


class TestSync:
    """Синхронизация официальных дней — идемпотентна и не трогает сегодня."""

    @pytest.mark.asyncio
    async def test_repeated_sync_does_not_double(self, db_session):
        now = _utc(datetime(2026, 9, 10, 12, 0))
        today = now.date()
        days = {
            today - timedelta(days=2): Decimal("12.50"),
            today - timedelta(days=1): Decimal("7.25"),
        }
        with patch.object(
            balance_service.anthropic_admin,
            "fetch_cost_days",
            AsyncMock(return_value=dict(days)),
        ):
            await balance_service.sync_cost_days(db_session, now=now)
            await balance_service.sync_cost_days(db_session, now=now)

        rows = (await db_session.execute(select(ApiCostDay))).scalars().all()
        assert len(rows) == 2
        assert sum(float(r.amount_usd) for r in rows) == pytest.approx(19.75)

    @pytest.mark.asyncio
    async def test_new_amount_overwrites_old(self, db_session):
        """День дозаполнился у Anthropic — перезаписываем, а не складываем."""
        now = _utc(datetime(2026, 9, 10, 12, 0))
        yesterday = now.date() - timedelta(days=1)
        with patch.object(
            balance_service.anthropic_admin,
            "fetch_cost_days",
            AsyncMock(return_value={yesterday: Decimal("5.00")}),
        ):
            await balance_service.sync_cost_days(db_session, now=now)
        with patch.object(
            balance_service.anthropic_admin,
            "fetch_cost_days",
            AsyncMock(return_value={yesterday: Decimal("9.00")}),
        ):
            await balance_service.sync_cost_days(db_session, now=now)

        row = (await db_session.execute(select(ApiCostDay))).scalars().one()
        assert float(row.amount_usd) == pytest.approx(9.0)

    @pytest.mark.asyncio
    async def test_current_day_never_stored(self, db_session):
        """Сегодняшний бакет неполон: записать его — потерять часть трат.

        Сегодняшний день считает `api_call_log`; появись он ещё и в официальной
        таблице, часть трат была бы вычтена дважды.
        """
        now = _utc(datetime(2026, 9, 10, 12, 0))
        today = now.date()
        with patch.object(
            balance_service.anthropic_admin,
            "fetch_cost_days",
            AsyncMock(return_value={today: Decimal("3.00"), today - timedelta(days=1): Decimal("4.00")}),
        ):
            written = await balance_service.sync_cost_days(db_session, now=now)

        assert written == 1
        rows = (await db_session.execute(select(ApiCostDay))).scalars().all()
        assert [r.day for r in rows] == [today - timedelta(days=1)]

    @pytest.mark.asyncio
    async def test_without_admin_key_returns_none(self, db_session):
        now = _utc(datetime(2026, 9, 10, 12, 0))
        with patch.object(
            balance_service.anthropic_admin,
            "fetch_cost_days",
            AsyncMock(return_value=None),
        ):
            assert await balance_service.sync_cost_days(db_session, now=now) is None


class TestSyncRace:
    @pytest.mark.asyncio
    async def test_concurrent_sync_does_not_crash(self, db_session):
        """Часовой job и кнопка «Сверить» могут попасть в один день разом.

        Проигравший обязан молча откатиться: данные уже записаны победителем.
        """
        now = _utc(datetime(2026, 9, 10, 12, 0))
        yesterday = now.date() - timedelta(days=1)

        async def fake_commit():
            raise IntegrityError("insert", {}, Exception("duplicate key"))

        with patch.object(
            balance_service.anthropic_admin,
            "fetch_cost_days",
            AsyncMock(return_value={yesterday: Decimal("5.00")}),
        ), patch.object(db_session, "commit", fake_commit):
            written = await balance_service.sync_cost_days(db_session, now=now)

        assert written == 0
