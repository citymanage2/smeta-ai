"""Остаток денег на Claude API — чтение и отметка баланса.

Читать и отмечать может руководитель (как и весь дашборд «Система»): вопрос
«хватит ли денег до конца недели» — управленческий, а отметка баланса меняет
цифру, на которую смотрят все.

Расчёт живёт целиком в `balance_service`: роутер только раскладывает снимок по
полям ответа. Второй точки, где из отметок и трат получается остаток, быть не
должно — разошлись бы молча.

План: plans/2026-09-01-ostatok-deneg-na-api.md, Фаза 5.
"""
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.api_balance import ApiBalanceMark
from app.services import balance_service
from app.utils.permissions import get_manager_user

logger = structlog.get_logger()

router = APIRouter(prefix="/api-balance", tags=["api-balance"])

# Разумные границы суммы: ноль и минус — не баланс, а сумма выше миллиона почти
# наверняка опечатка (лишний ноль). Пропустить её — надолго показать неправду.
MAX_BALANCE_USD = Decimal("1000000")


class BalanceMarkIn(BaseModel):
    balance_usd: Decimal = Field(..., gt=0, le=MAX_BALANCE_USD)
    measured_on: Optional[date] = None
    note: Optional[str] = Field(None, max_length=500)


class BalanceMarkOut(BaseModel):
    id: int
    balance_usd: float
    measured_on: date
    note: Optional[str]
    created_by: Optional[str]
    created_at: datetime


class BalanceResponse(BaseModel):
    """Снимок остатка. `remaining_usd = null` — отметки нет, считать не от чего."""

    mark_usd: Optional[float]
    mark_on: Optional[date]
    official_usd: float
    live_usd: float
    spent_usd: float
    remaining_usd: Optional[float]
    official_through: Optional[date]
    synced_at: Optional[datetime]
    official_enabled: bool
    avg_daily_usd: float
    days_left: Optional[float]
    avg_estimate_usd: Optional[float]
    estimates_left: Optional[int]
    level: str
    marks: list[BalanceMarkOut]


def _mark_out(row: ApiBalanceMark) -> BalanceMarkOut:
    return BalanceMarkOut(
        id=row.id,
        balance_usd=float(row.balance_usd),
        measured_on=row.measured_on,
        note=row.note,
        created_by=row.created_by,
        created_at=row.created_at,
    )


async def _recent_marks(db: AsyncSession, limit: int = 10) -> list[BalanceMarkOut]:
    rows = (
        (
            await db.execute(
                select(ApiBalanceMark)
                .order_by(ApiBalanceMark.measured_on.desc(), ApiBalanceMark.id.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [_mark_out(r) for r in rows]


@router.get("", response_model=BalanceResponse)
async def get_balance(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_manager_user),
):
    """Сколько осталось, на сколько хватит и когда последний раз сверялись."""
    snap = await balance_service.compute_balance(db)
    return BalanceResponse(
        mark_usd=snap.mark_usd,
        mark_on=snap.mark_on,
        official_usd=round(snap.official_usd, 4),
        live_usd=round(snap.live_usd, 4),
        spent_usd=round(snap.spent_usd, 4),
        remaining_usd=round(snap.remaining_usd, 2) if snap.remaining_usd is not None else None,
        official_through=snap.official_through,
        synced_at=snap.synced_at,
        official_enabled=snap.official_enabled,
        avg_daily_usd=round(snap.avg_daily_usd, 4),
        days_left=round(snap.days_left, 1) if snap.days_left is not None else None,
        avg_estimate_usd=round(snap.avg_estimate_usd, 2)
        if snap.avg_estimate_usd is not None
        else None,
        estimates_left=snap.estimates_left,
        level=snap.level,
        marks=await _recent_marks(db),
    )


@router.post("/marks", response_model=BalanceResponse, status_code=status.HTTP_201_CREATED)
async def create_mark(
    payload: BalanceMarkIn,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_manager_user),
):
    """Записать «в Console на дату D было $X» — точку отсчёта для остатка."""
    measured_on = payload.measured_on or datetime.now(timezone.utc).date()
    if measured_on > datetime.now(timezone.utc).date():
        # Отметка из будущего сделала бы отрицательным период трат: всё, что
        # потрачено, оказалось бы «до отметки» и просто исчезло из расчёта.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Дата отметки не может быть в будущем",
        )

    mark = ApiBalanceMark(
        balance_usd=payload.balance_usd,
        measured_on=measured_on,
        note=payload.note,
        created_by=current_user.get("email") or current_user.get("name"),
    )
    db.add(mark)
    await db.commit()
    logger.info(
        "API balance mark created",
        balance_usd=float(payload.balance_usd),
        measured_on=str(measured_on),
    )
    return await get_balance(db=db, _=current_user)


@router.delete("/marks/{mark_id}", response_model=BalanceResponse)
async def delete_mark(
    mark_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_manager_user),
):
    """Удалить ошибочную отметку — опечатка в сумме иначе врёт до следующей."""
    mark = (
        (await db.execute(select(ApiBalanceMark).where(ApiBalanceMark.id == mark_id)))
        .scalars()
        .first()
    )
    if mark is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Отметка не найдена")
    await db.delete(mark)
    await db.commit()
    return await get_balance(db=db, _=current_user)


@router.post("/sync", response_model=BalanceResponse)
async def sync_now(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_manager_user),
):
    """Сверить траты с Anthropic прямо сейчас, не дожидаясь часового цикла.

    Отказ Anthropic не роняет ответ: остаток продолжает считаться по своему
    журналу, а на странице видно, когда была последняя удачная сверка.
    """
    from app.services.anthropic_admin import AdminApiError

    try:
        await balance_service.sync_cost_days(db)
    except AdminApiError as exc:
        logger.warning("Manual cost sync failed", error=str(exc))
    return await get_balance(db=db, _=current_user)
