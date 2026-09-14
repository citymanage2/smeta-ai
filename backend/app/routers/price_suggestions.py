"""HTTP-контракт очереди предложений цены.

План: plans/2026-09-10-sverka-i-obuchenie-na-pravkah.md, Фаза 6.

Доступ — любому сотруднику (решение пользователя 10.09.2026): задачи в сервисе
общие, и подтверждать цену логично тому, кто её и правил. Управленческий отчёт
«Правки» при этом остаётся менеджерским, как был.

Ничего не применяется само: список только читает журнал, а запись в прайс
происходит исключительно в ответ на `POST /accept` — то есть на нажатие
человека (правило 9 CLAUDE.md).
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services import price_suggestions
from app.services.document_service import user_display_name
from app.utils.auth import get_current_user

router = APIRouter(prefix="/price-suggestions", tags=["price-suggestions"])


class Suggestion(BaseModel):
    name_key: str
    display_name: str
    row_type: str
    unit: str
    suggested_price: float
    min_price: float
    max_price: float
    system_price: Optional[float] = None
    touches: int
    tasks: int
    sources: list[str] = []
    prices_disagree: bool = False
    user_name: Optional[str] = None
    last_at: Optional[str] = None
    decision: Optional[str] = None


class DecisionRequest(BaseModel):
    name: str = Field(min_length=1)
    row_type: str = "work"
    unit: str = ""
    # Цену можно поправить перед подтверждением: человек — источник истины, а
    # не арбитр «да/нет» над числом, которое посчитала система.
    price: Optional[float] = None


def _current_user_id(current_user: dict) -> Optional[int]:
    raw = current_user.get("user_id") or current_user.get("id")
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


@router.get("", response_model=list[Suggestion])
async def list_suggestions(
    min_touches: int = Query(default=price_suggestions.DEFAULT_MIN_TOUCHES, ge=1, le=50),
    decided: bool = Query(default=False, description="Показать решённые"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Что накопилось: «система посчитала X — вы поставили Y, N раз»."""
    items = await price_suggestions.collect(
        db, min_touches=min_touches, include_decided=decided
    )
    if decided:
        # Вкладка решённых показывает ровно те, по которым решение уже есть.
        items = [item for item in items if item.get("decision")]
    return [Suggestion(**item) for item in items]


@router.post("/accept")
async def accept_suggestion(
    body: DecisionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Запомнить цену: она уходит в прайс под «Из смет»."""
    if body.price is None or body.price <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Цена должна быть больше нуля",
        )
    try:
        result = await price_suggestions.accept(
            db,
            name=body.name, row_type=body.row_type, unit=body.unit,
            price=body.price,
            user_id=_current_user_id(current_user),
            user_name=await user_display_name(db, current_user),
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error

    if not result.get("written"):
        # Единица позиции не сводится с единицей прайса — цена за мешок не
        # ложится в позицию с ценой за килограмм (правило 8). Молчать нельзя.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Цена не записана: единица позиции не сводится с единицей "
                "в прайсе. Поправьте единицу в каталоге цен."
            ),
        )
    return result


@router.post("/reject")
async def reject_suggestion(
    body: DecisionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Не запоминать. В прайс не пишется ничего."""
    return await price_suggestions.reject(
        db,
        name=body.name, row_type=body.row_type, unit=body.unit, price=body.price,
        user_id=_current_user_id(current_user),
        user_name=await user_display_name(db, current_user),
    )


@router.post("/undo")
async def undo_decision(
    body: DecisionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Вернуть предложение в очередь: решение снимается.

    Цену из прайса это не убирает — там она уже живёт своей жизнью и правится
    в каталоге.
    """
    return await price_suggestions.undo(
        db, name=body.name, row_type=body.row_type, unit=body.unit
    )
