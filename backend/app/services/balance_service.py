"""Сколько денег осталось на Claude API — единственная точка расчёта.

Остатка не отдаёт ни один эндпоинт Anthropic. Считаем сами, от последней отметки
человека («в Console на дату D было $X») минус всё, что потрачено после неё:

    остаток = отметка − официальные траты закрытых дней − траты сегодняшнего дня

Два источника трат и жёсткая граница между ними:

* **закрытые дни** — `api_cost_days`, официальные суммы Anthropic. Точны до цента,
  но приходят с задержкой и только дневными бакетами;
* **сегодняшний день** — `api_call_log`, наш собственный счёт стоимости вызовов.
  Мгновенный: смета, посчитанная минуту назад, уже видна в остатке.

Граница — начало текущего дня UTC. Ровно так, а не «сейчас минус N минут»:
документация обещает появление официальных данных за 5 минут и честно
предупреждает, что бывает дольше. Ошибка в границе — это не неточность, это
трата, вычтенная дважды или потерянная совсем.

Дни, за которые официальных данных нет (админ-ключ не подключён, синхронизация
не доходила), закрываются собственным журналом — но каждый день считается ровно
один раз. Для этого официальным считается только НЕПРЕРЫВНЫЙ хвост дней до
вчерашнего включительно: дырка в середине сделала бы «официальную» сумму
неполной, а сопоставлять дырки по дням значило бы группировать журнал по датам —
операция, которая на PostgreSQL и SQLite ведёт себя по-разному, а расхождение
диалектов в расчёте денег недопустимо.

План: plans/2026-09-01-ostatok-deneg-na-api.md, Фаза 4.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Optional

import structlog
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_balance import ApiBalanceMark, ApiCostDay
from app.models.api_call_log import ApiCallLog
from app.models.task import Task
from app.services import anthropic_admin

logger = structlog.get_logger()

# Сколько последних дней перечитывать при каждой синхронизации. Одного мало:
# вчерашний день дозаполняется какое-то время после полуночи UTC, и записанная
# сразу после неё сумма оказалась бы неполной навсегда.
SYNC_DAYS = 3
# Окно для среднего темпа расхода. Неделя сглаживает «в понедельник считали три
# сметы, во вторник ни одной» и при этом не тянет в прогноз позапрошлый месяц.
PACE_WINDOW_DAYS = 7
# Окно для средней стоимости одной сметы.
ESTIMATE_WINDOW_DAYS = 30
# Меньше трёх смет — среднее считать не по чему, прогноз «на N смет» не показываем.
MIN_ESTIMATES_FOR_AVG = 3
# Пороги тревоги — в днях работы по текущему темпу, а не в долларах: $50 для
# одного месяца это запас, для другого — полдня. Настраивать нечего.
WARN_DAYS = 3.0
ALARM_DAYS = 1.0

ESTIMATE_TASK_TYPE = "ESTIMATE_FROM_LIST"


@dataclass(frozen=True)
class BalanceSnapshot:
    """Что показать про деньги на счёте прямо сейчас."""

    # Точка отсчёта: последняя отметка человека.
    mark_usd: Optional[float] = None
    mark_on: Optional[date] = None
    # Потрачено после отметки.
    official_usd: float = 0.0
    live_usd: float = 0.0
    spent_usd: float = 0.0
    # Остаток. None — отметки нет, считать не от чего.
    remaining_usd: Optional[float] = None
    # По какой день включительно траты подтверждены Anthropic.
    official_through: Optional[date] = None
    synced_at: Optional[datetime] = None
    official_enabled: bool = False
    # Прогноз.
    avg_daily_usd: float = 0.0
    days_left: Optional[float] = None
    avg_estimate_usd: Optional[float] = None
    estimates_left: Optional[int] = None
    # ok | warn | alarm | unknown
    level: str = "unknown"


def _day_start(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=timezone.utc)


async def _sum_calls(
    db: AsyncSession, since: datetime, until: Optional[datetime] = None
) -> float:
    """Сумма стоимости вызовов из своего журнала за интервал [since, until)."""
    stmt = select(func.coalesce(func.sum(ApiCallLog.cost_usd), 0)).where(
        ApiCallLog.called_at >= since
    )
    if until is not None:
        stmt = stmt.where(ApiCallLog.called_at < until)
    return float((await db.execute(stmt)).scalar_one() or 0)


async def _latest_mark(db: AsyncSession) -> Optional[ApiBalanceMark]:
    """Последняя отметка: по дате, а при равенстве — по id (позже внесённая)."""
    return (
        (
            await db.execute(
                select(ApiBalanceMark)
                .order_by(ApiBalanceMark.measured_on.desc(), ApiBalanceMark.id.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )


async def _official_tail(
    db: AsyncSession, start: date, today: date
) -> tuple[float, Optional[date], Optional[date], Optional[datetime]]:
    """Официальные траты непрерывным хвостом до вчерашнего дня включительно.

    Возвращает (сумма, первый официальный день, последний официальный день,
    время последней синхронизации). Хвост, а не «все найденные дни»: пропущенный
    день внутри периода означал бы, что часть трат не учтена ни официально, ни
    локально, — а так недостающее начало закрывается собственным журналом.
    """
    last_closed = today - timedelta(days=1)
    if last_closed < start:
        return 0.0, None, None, None

    rows = (
        (
            await db.execute(
                select(ApiCostDay)
                .where(ApiCostDay.day >= start, ApiCostDay.day <= last_closed)
                .order_by(ApiCostDay.day.desc())
            )
        )
        .scalars()
        .all()
    )
    if not rows or rows[0].day != last_closed:
        # Вчерашний день ещё не синхронизирован — официальному хвосту не на что
        # опереться, считаем весь период по своему журналу.
        return 0.0, None, None, None

    total = Decimal("0")
    expected = last_closed
    first_day = last_closed
    synced_at: Optional[datetime] = None
    for row in rows:
        if row.day != expected:
            break  # дырка — дальше в прошлое хвост не продолжается
        total += row.amount_usd
        first_day = row.day
        if synced_at is None or (row.synced_at and row.synced_at > synced_at):
            synced_at = row.synced_at
        expected = row.day - timedelta(days=1)

    return float(total), first_day, last_closed, synced_at


async def _avg_estimate_cost(db: AsyncSession, now: datetime) -> Optional[float]:
    """Средняя стоимость одной сметы за месяц — «на сколько смет ещё хватит»."""
    since = now - timedelta(days=ESTIMATE_WINDOW_DAYS)
    rows = (
        await db.execute(
            select(
                ApiCallLog.task_id,
                func.sum(ApiCallLog.cost_usd).label("cost"),
            )
            .join(Task, ApiCallLog.task_id == Task.id)
            .where(
                ApiCallLog.called_at >= since,
                Task.task_type == ESTIMATE_TASK_TYPE,
                Task.status == "completed",
            )
            .group_by(ApiCallLog.task_id)
        )
    ).all()
    costs = [float(r.cost or 0) for r in rows if float(r.cost or 0) > 0]
    if len(costs) < MIN_ESTIMATES_FOR_AVG:
        return None
    return sum(costs) / len(costs)


async def compute_balance(
    db: AsyncSession, now: Optional[datetime] = None
) -> BalanceSnapshot:
    """Остаток, темп расхода и прогноз — один снимок для страницы «Система»."""
    now = now or datetime.now(timezone.utc)
    today = now.date()
    today_start = _day_start(today)

    # Темп расхода считаем всегда — он не зависит от наличия отметки.
    pace_total = await _sum_calls(db, now - timedelta(days=PACE_WINDOW_DAYS))
    avg_daily = pace_total / PACE_WINDOW_DAYS
    avg_estimate = await _avg_estimate_cost(db, now)
    official_enabled = anthropic_admin.is_configured()

    mark = await _latest_mark(db)
    if mark is None:
        return BalanceSnapshot(
            avg_daily_usd=avg_daily,
            avg_estimate_usd=avg_estimate,
            official_enabled=official_enabled,
            level="unknown",
        )

    start = mark.measured_on
    start_dt = _day_start(start)

    official_usd, official_from, official_through, synced_at = await _official_tail(
        db, start, today
    )
    # Дни от отметки до начала официального хвоста — по своему журналу.
    local_before = await _sum_calls(
        db,
        start_dt,
        _day_start(official_from) if official_from else today_start,
    )
    live_usd = await _sum_calls(db, today_start)

    spent = official_usd + local_before + live_usd
    remaining = float(mark.balance_usd) - spent

    days_left = remaining / avg_daily if avg_daily > 0 else None
    estimates_left = (
        int(remaining // avg_estimate)
        if avg_estimate and avg_estimate > 0 and remaining > 0
        else (0 if avg_estimate else None)
    )

    if days_left is None:
        level = "alarm" if remaining <= 0 else "ok"
    elif days_left < ALARM_DAYS:
        level = "alarm"
    elif days_left < WARN_DAYS:
        level = "warn"
    else:
        level = "ok"

    return BalanceSnapshot(
        mark_usd=float(mark.balance_usd),
        mark_on=mark.measured_on,
        official_usd=official_usd,
        live_usd=live_usd,
        spent_usd=spent,
        remaining_usd=remaining,
        official_through=official_through,
        synced_at=synced_at,
        official_enabled=official_enabled,
        avg_daily_usd=avg_daily,
        days_left=days_left,
        avg_estimate_usd=avg_estimate,
        estimates_left=estimates_left,
        level=level,
    )


async def sync_cost_days(
    db: AsyncSession, now: Optional[datetime] = None
) -> Optional[int]:
    """Перечитать последние дни из `cost_report` и записать их. None — ключа нет.

    Возвращает число записанных дней. Идемпотентна: ключ таблицы — сам день,
    повторный прогон переписывает строку той же суммой.
    """
    now = now or datetime.now(timezone.utc)
    today = now.date()
    start = today - timedelta(days=SYNC_DAYS)

    # Текущий день не запрашиваем: его бакет неполон, а записанная неполная
    # сумма означала бы, что часть сегодняшних трат не увидит ни один источник.
    days = await anthropic_admin.fetch_cost_days(start, today)
    if days is None:
        return None

    existing = {
        row.day: row
        for row in (
            (
                await db.execute(
                    select(ApiCostDay).where(
                        ApiCostDay.day >= start, ApiCostDay.day < today
                    )
                )
            )
            .scalars()
            .all()
        )
    }

    written = 0
    for day, amount in days.items():
        if day >= today:
            continue
        row = existing.get(day)
        if row is None:
            db.add(ApiCostDay(day=day, amount_usd=amount, synced_at=now))
        else:
            row.amount_usd = amount
            row.synced_at = now
        written += 1

    try:
        await db.commit()
    except IntegrityError:
        # Тот же день вставляют одновременно часовой job воркера и кнопка
        # «Сверить траты» из админки — разные процессы, общий первичный ключ.
        # Проигравший откатывается молча: данные уже записаны победителем, и
        # ронять из-за этого страницу не за что.
        await db.rollback()
        logger.info("Cost report sync raced with another sync", days=written)
        return 0

    logger.info("Cost report synced", days=written, start=str(start), end=str(today))
    return written
