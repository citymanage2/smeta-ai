"""Отчёт по журналу корректировок: где система врёт чаще всего.

План: plans/2026-08-07-obuchenie-na-korrektirovkah.md, Фаза 2.

Отчёт строится только по первым касаниям ячеек (`is_first_touch`): вторая
правка той же ячейки — разговор человека с самим собой, ошибкой системы не
является. Лента последних расхождений показывает всё, включая повторные, —
там это история работы, а не метрика качества.

Доступ — менеджерам (админ и руководитель отдела продаж): это управленческая
метрика качества сервиса, а не персональные данные конкретного менеджера.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.correction_signal import CorrectionSignal
from app.utils.auth import get_current_user
from app.utils.permissions import is_manager

router = APIRouter(prefix="/corrections", tags=["corrections"])

# Сколько строк отдаём в рейтингах. Пользователей у сервиса единицы, а смысл
# отчёта — верхушка списка: длинный хвост правок ничего не объясняет.
TOP_LIMIT = 10
# Потолок ленты последних расхождений.
MAX_FEED = 200


class FieldStat(BaseModel):
    field: str
    document_kind: str
    count: int


class PositionStat(BaseModel):
    row_name: str
    document_kind: str
    count: int


class KindStat(BaseModel):
    document_kind: str
    count: int


class CorrectionsStats(BaseModel):
    total: int
    first_touch: int
    # Сколько правок затронули цену — по ним пойдёт уровень 2 («запомнить цену?»).
    price_edits: int
    rows_added: int
    rows_removed: int
    top_fields: list[FieldStat]
    top_positions: list[PositionStat]
    by_kind: list[KindStat]


class CorrectionOut(BaseModel):
    id: str
    task_id: str
    document_kind: str
    row_name: str = ""
    row_type: Optional[str] = None
    unit: Optional[str] = None
    field: str
    previous_value: Optional[str] = None
    new_value: Optional[str] = None
    is_first_touch: bool
    price_source: Optional[str] = None
    user_name: Optional[str] = None
    created_at: str


# Поля, которые считаем ценой. Смета зовёт их машинными ключами, перечень и
# полнота — заголовками колонок исходного файла.
_PRICE_FIELDS = ("price_work", "price_material")
_PRICE_HINT = "цена"


def _require_manager(current_user: dict) -> None:
    if not is_manager(current_user.get("role")):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Отчёт по правкам доступен руководителю",
        )


def _is_price_field(field: str) -> bool:
    return field in _PRICE_FIELDS or _PRICE_HINT in field.lower()


@router.get("/stats", response_model=CorrectionsStats)
async def get_stats(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Сводка: сколько накоплено сигналов и что правят чаще всего."""
    _require_manager(current_user)

    total = await db.scalar(select(func.count()).select_from(CorrectionSignal)) or 0
    first_touch = await db.scalar(
        select(func.count()).select_from(CorrectionSignal)
        .where(CorrectionSignal.is_first_touch.is_(True))
    ) or 0

    # Добавленные и удалённые строки — сигнал «пропустили позицию» и «выдумали
    # лишнюю»; у них поле-заполнитель, поэтому считаем по значению.
    rows_added = await db.scalar(
        select(func.count()).select_from(CorrectionSignal)
        .where(CorrectionSignal.new_value == "добавлена")
    ) or 0
    rows_removed = await db.scalar(
        select(func.count()).select_from(CorrectionSignal)
        .where(CorrectionSignal.new_value == "удалена")
    ) or 0

    fields_res = await db.execute(
        select(
            CorrectionSignal.field,
            CorrectionSignal.document_kind,
            func.count().label("cnt"),
        )
        .where(CorrectionSignal.is_first_touch.is_(True))
        .group_by(CorrectionSignal.field, CorrectionSignal.document_kind)
        .order_by(func.count().desc())
        .limit(TOP_LIMIT)
    )
    top_fields = [
        FieldStat(field=field, document_kind=kind, count=count)
        for field, kind, count in fields_res.all()
    ]

    positions_res = await db.execute(
        select(
            CorrectionSignal.row_name,
            CorrectionSignal.document_kind,
            func.count().label("cnt"),
        )
        .where(
            CorrectionSignal.is_first_touch.is_(True),
            CorrectionSignal.row_name.isnot(None),
            CorrectionSignal.row_name != "",
        )
        .group_by(CorrectionSignal.row_name, CorrectionSignal.document_kind)
        .order_by(func.count().desc())
        .limit(TOP_LIMIT)
    )
    top_positions = [
        PositionStat(row_name=name, document_kind=kind, count=count)
        for name, kind, count in positions_res.all()
    ]

    kinds_res = await db.execute(
        select(CorrectionSignal.document_kind, func.count().label("cnt"))
        .group_by(CorrectionSignal.document_kind)
        .order_by(func.count().desc())
    )
    by_kind = [
        KindStat(document_kind=kind, count=count) for kind, count in kinds_res.all()
    ]

    # Цену считаем в питоне: у перечня и полноты имя колонки произвольное
    # («Цена работ», «Цена, руб»), и SQL-условие на все варианты не написать.
    price_res = await db.execute(
        select(CorrectionSignal.field, func.count().label("cnt"))
        .where(CorrectionSignal.is_first_touch.is_(True))
        .group_by(CorrectionSignal.field)
    )
    price_edits = sum(count for field, count in price_res.all() if _is_price_field(field))

    return CorrectionsStats(
        total=total,
        first_touch=first_touch,
        price_edits=price_edits,
        rows_added=rows_added,
        rows_removed=rows_removed,
        top_fields=top_fields,
        top_positions=top_positions,
        by_kind=by_kind,
    )


@router.get("", response_model=list[CorrectionOut])
async def list_corrections(
    limit: int = Query(default=50, ge=1, le=MAX_FEED),
    first_touch_only: bool = Query(default=True),
    document_kind: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Последние расхождения: «система посчитала X — человек поставил Y»."""
    _require_manager(current_user)

    query = select(CorrectionSignal).order_by(CorrectionSignal.created_at.desc())
    if first_touch_only:
        query = query.where(CorrectionSignal.is_first_touch.is_(True))
    if document_kind:
        query = query.where(CorrectionSignal.document_kind == document_kind)

    res = await db.execute(query.limit(limit))
    return [
        CorrectionOut(
            id=str(s.id),
            task_id=str(s.task_id),
            document_kind=s.document_kind,
            row_name=s.row_name or "",
            row_type=s.row_type,
            unit=s.unit,
            field=s.field,
            previous_value=s.previous_value,
            new_value=s.new_value,
            is_first_touch=s.is_first_touch,
            price_source=s.price_source,
            user_name=s.user_name,
            created_at=s.created_at.isoformat() if s.created_at else "",
        )
        for s in res.scalars().all()
    ]
