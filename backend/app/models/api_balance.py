"""Остаток денег на Claude API: отметки баланса и официальные траты по дням.

У Anthropic нет и не было эндпоинта «сколько осталось на счёте» — ни в SDK, ни в
Admin API. Отдаётся только «сколько потрачено» (`cost_report`, дневные бакеты с
задержкой ~5 минут). Значит точку отсчёта может дать только человек.

Отсюда две таблицы:

* `api_balance_marks` — отметка: «в Console на такую-то дату на счету было $X».
  Именно отметка остатка, а не история пополнений. Пополнения пришлось бы
  вводить ВСЕ и ничего не забыть — забыл одно, и цифра врёт навсегда. Отметка
  же самокорректируется: любая новая обнуляет накопленную ошибку, потому что
  расчёт всегда идёт от последней.
* `api_cost_days` — что Anthropic официально списал за каждый ЗАКРЫТЫЙ день.
  Заполняется фоновой синхронизацией, ключ — сам день, поэтому повторный прогон
  перезаписывает строку, а не добавляет вторую.

Траты за ТЕКУЩИЙ день в `api_cost_days` не попадают никогда: их считает
`api_call_log` в тот же момент, когда задача сожгла деньги. Граница между
источниками — начало текущего дня UTC. Двигать её к «сейчас минус N минут»
нельзя: документация обещает появление данных за 5 минут и честно предупреждает,
что бывает дольше, а ошибка в границе означает либо двойной учёт траты, либо её
потерю.

План: plans/2026-09-01-ostatok-deneg-na-api.md, Фаза 2.
"""
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import Date, Integer, Numeric, String, TIMESTAMP, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ApiBalanceMark(Base):
    """«На дату D на счету было $X» — точка отсчёта для остатка."""

    __tablename__ = "api_balance_marks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    balance_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    # Дата, а не время: в Console видна сумма «сейчас», точное время человек не
    # знает и спрашивать его — просить точность, которой нет. Траты этого дня
    # вычитаются целиком (см. balance_service): остаток может оказаться занижен
    # на расход одного дня, и это намеренно безопасная сторона ошибки.
    measured_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class ApiCostDay(Base):
    """Официальная стоимость одного закрытого дня из `cost_report` Anthropic.

    `day` — первичный ключ, поэтому синхронизация идемпотентна по построению:
    перечитать последние дни и записать их заново нельзя «дважды».
    Суммы в долларах: из ответа API они приходят в центах строкой и переводятся
    на границе (`anthropic_admin.fetch_cost_days`), чтобы дальше по коду ходила
    одна единица измерения.
    """

    __tablename__ = "api_cost_days"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    amount_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    synced_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
