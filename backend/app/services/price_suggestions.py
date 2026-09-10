"""Очередь предложений: «система посчитала 3000, вы поставили 2500 — запомнить?»

План: plans/2026-09-10-sverka-i-obuchenie-na-pravkah.md, Фаза 6.

Предложения считаются из журнала корректировок на лету и **нигде не хранятся**.
Хранить их значило бы держать вторую копию знания в согласии с растущим
журналом; в базе лежат только решения человека (`price_decisions`).

Четыре правила, без которых это опасная функция, а не полезная:

1. **Ничего не применяется без нажатия человеком** (правило 9 CLAUDE.md). Этот
   модуль умеет считать и показывать; записывает он только по прямому вызову
   `accept`, за которым стоит кнопка.
2. **Только смета.** У перечня и полноты поле — это заголовок колонки чужого
   файла: из «Цена за ед., руб.» не понять, работа это или материал, а тип и
   единица там могут отсутствовать вовсе. Без типа и единицы писать в прайс
   нельзя (правило 8), поэтому такие сигналы идут в отчёт, но не в очередь.
3. **Предлагается медиана, а не последняя правка.** Одно наблюдение — это одна
   опечатка: 25000 вместо 2500 уехало бы в цену «Из смет», которая перебивает
   все прайсы подрядчиков (`price_min`). Медиана из двух — их среднее, из трёх
   и более — настоящая медиана; и то и другое устойчивее последнего значения.
4. **Запись идёт единственным существующим путём** — `price_bulk.add_items`.
   Он уже умеет всё, что нужно: пишет под «Из смет», не трогает цены
   подрядчиков, сверяет единицы (правило 8), двигает дату только при реальной
   переоценке (правило 15) и перезагружает кеш цен. Второй путь записи означал
   бы, что одна и та же цена ложится в прайс по-разному.
"""
from __future__ import annotations

from statistics import median
from typing import Optional

import structlog
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.correction_signal import CorrectionSignal
from app.models.price_decision import (
    DECISION_ACCEPTED, DECISION_REJECTED, PriceDecision,
)
from app.services.embedding_service import normalize_name

logger = structlog.get_logger()

# Поля цены в смете. У перечня и полноты имена колонок произвольные — они сюда
# намеренно не попадают (см. правило 2 в шапке модуля).
PRICE_FIELDS = ("price_work", "price_material")
FIELD_TO_TYPE = {"price_work": "work", "price_material": "material"}

# Сколько раз человек должен поправить цену позиции, чтобы это стало
# предложением. Одна правка — случай, две — уже закономерность.
DEFAULT_MIN_TOUCHES = 2

# Насколько новая медиана должна отличаться от отклонённой, чтобы предложение
# всплыло снова. Меньше — то же самое знание, человек уже сказал «нет».
REPEAT_THRESHOLD_PCT = 10.0

# Во сколько раз цены внутри одной позиции могут разойтись, прежде чем мы
# перестанем что-либо предлагать по умолчанию: это уже не «уточнение цены», а
# разные вещи под одним названием.
SPREAD_LIMIT = 1.5

MAX_SUGGESTIONS = 100


def _decision_key(name: str, row_type: str, unit: Optional[str]) -> tuple:
    return (normalize_name(name), row_type, (unit or "").strip().lower())


def _spread(values: list) -> float:
    low, high = min(values), max(values)
    return (high / low) if low > 0 else 0.0


async def collect(
    db: AsyncSession,
    *,
    min_touches: int = DEFAULT_MIN_TOUCHES,
    include_decided: bool = False,
) -> list[dict]:
    """Что накопилось и готово к подтверждению.

    Возвращает список предложений, самые частые — первыми: подтверждать имеет
    смысл то, что встречается чаще, а не то, что случилось последним.
    """
    signals = (await db.execute(
        select(CorrectionSignal).where(
            CorrectionSignal.is_first_touch.is_(True),
            CorrectionSignal.document_kind == "estimate",
            CorrectionSignal.field.in_(PRICE_FIELDS),
            CorrectionSignal.new_num.isnot(None),
            or_(
                CorrectionSignal.row_name.isnot(None),
                CorrectionSignal.row_name != "",
            ),
        ).order_by(CorrectionSignal.created_at)
    )).scalars().all()

    groups: dict[tuple, dict] = {}
    for signal in signals:
        name = (signal.row_name or "").strip()
        if not name:
            continue
        row_type = FIELD_TO_TYPE.get(signal.field or "", "work")
        key = _decision_key(name, row_type, signal.unit)

        group = groups.setdefault(key, {
            "name_key": key[0],
            "display_name": name,
            "row_type": row_type,
            "unit": (signal.unit or "").strip(),
            "prices": [],
            "system_prices": [],
            "sources": {},
            "tasks": set(),
            "last_at": None,
            "user_name": None,
        })
        group["prices"].append(float(signal.new_num))
        if signal.previous_num is not None:
            group["system_prices"].append(float(signal.previous_num))
        if signal.price_source:
            group["sources"][signal.price_source] = (
                group["sources"].get(signal.price_source, 0) + 1
            )
        group["tasks"].add(str(signal.task_id))
        group["last_at"] = signal.created_at
        group["user_name"] = signal.user_name or group["user_name"]

    decisions = {
        (d.name_key, d.row_type, d.unit): d
        for d in (await db.execute(select(PriceDecision))).scalars().all()
    }

    suggestions = []
    for key, group in groups.items():
        prices = group["prices"]
        if len(prices) < min_touches:
            continue

        suggested = round(float(median(prices)), 2)
        if suggested <= 0:
            # Ноль и минус ценой не бывают: такую правку («стёр цену») в прайс
            # не понесёшь, она означает «цены нет», а не «цена ноль».
            continue

        decided = decisions.get(key)
        if decided is not None and not include_decided:
            # Отклонили именно эту цену. Та же цена — то же «нет»; заметно
            # другая — новое знание, и спросить снова честно.
            previous = decided.price or 0.0
            same = (
                previous > 0
                and abs(suggested - previous) / previous * 100 < REPEAT_THRESHOLD_PCT
            )
            if same or decided.decision == DECISION_ACCEPTED:
                continue

        spread = _spread(prices)
        suggestions.append({
            "name_key": key[0],
            "display_name": group["display_name"],
            "row_type": group["row_type"],
            "unit": group["unit"],
            "suggested_price": suggested,
            "min_price": round(min(prices), 2),
            "max_price": round(max(prices), 2),
            # Что система считала до правок — это и есть «ошибка системы».
            "system_price": (
                round(float(median(group["system_prices"])), 2)
                if group["system_prices"] else None
            ),
            "touches": len(prices),
            "tasks": len(group["tasks"]),
            "sources": sorted(
                group["sources"], key=group["sources"].get, reverse=True
            ),
            # Цены внутри позиции разошлись больше чем в полтора раза — сама
            # система выбирать из них не вправе, решает человек.
            "prices_disagree": spread > SPREAD_LIMIT,
            "user_name": group["user_name"],
            "last_at": group["last_at"].isoformat() if group["last_at"] else None,
            "decision": decided.decision if decided is not None else None,
        })

    suggestions.sort(key=lambda s: (s["touches"], s["tasks"]), reverse=True)
    return suggestions[:MAX_SUGGESTIONS]


async def _record_decision(
    db: AsyncSession,
    *,
    name_key: str,
    display_name: str,
    row_type: str,
    unit: str,
    decision: str,
    price: Optional[float],
    user_id: Optional[int],
    user_name: Optional[str],
) -> None:
    from datetime import datetime, timezone

    existing = (await db.execute(
        select(PriceDecision).where(
            PriceDecision.name_key == name_key,
            PriceDecision.row_type == row_type,
            PriceDecision.unit == unit,
        )
    )).scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if existing is None:
        db.add(PriceDecision(
            name_key=name_key, display_name=display_name, row_type=row_type,
            unit=unit, decision=decision, price=price,
            user_id=user_id, user_name=user_name,
        ))
    else:
        existing.decision = decision
        existing.price = price
        existing.display_name = display_name or existing.display_name
        existing.user_id = user_id
        existing.user_name = user_name
        existing.updated_at = now


async def accept(
    db: AsyncSession,
    *,
    name: str,
    row_type: str,
    unit: str,
    price: float,
    user_id: Optional[int],
    user_name: Optional[str],
) -> dict:
    """Запомнить цену: записать её в прайс и отметить решение.

    Цена и единица передаются дальше ровно такими, какими человек их видит в
    смете. Всю сверку единиц и пересчёт делает `price_bulk.add_items` — второго
    места, где это считается, быть не должно.
    """
    from app.services import price_bulk

    if price is None or float(price) <= 0:
        raise ValueError("Цена должна быть больше нуля")

    result = await price_bulk.add_items(db, [{
        "kind": "work" if row_type == "work" else "material",
        "name": name,
        "unit": unit,
        "price": float(price),
    }])

    written = bool(result.get("added") or result.get("updated"))
    if written:
        await _record_decision(
            db,
            name_key=normalize_name(name), display_name=name, row_type=row_type,
            unit=(unit or "").strip().lower(), decision=DECISION_ACCEPTED,
            price=float(price), user_id=user_id, user_name=user_name,
        )
        await db.commit()

    logger.info(
        "price_suggestion_accepted",
        name=name, row_type=row_type, unit=unit, price=price, written=written,
    )
    return {"written": written, **result}


async def reject(
    db: AsyncSession,
    *,
    name: str,
    row_type: str,
    unit: str,
    price: Optional[float],
    user_id: Optional[int],
    user_name: Optional[str],
) -> dict:
    """Не запоминать эту цену. В прайс не пишется ничего."""
    await _record_decision(
        db,
        name_key=normalize_name(name), display_name=name, row_type=row_type,
        unit=(unit or "").strip().lower(), decision=DECISION_REJECTED,
        price=float(price) if price else None,
        user_id=user_id, user_name=user_name,
    )
    await db.commit()
    return {"decision": DECISION_REJECTED}


async def undo(db: AsyncSession, *, name: str, row_type: str, unit: str) -> dict:
    """Снять решение: предложение снова попадёт в очередь.

    Нужно, потому что прайс общий, а одно ошибочное нажатие иначе закрывало бы
    позицию навсегда — и молча.
    """
    existing = (await db.execute(
        select(PriceDecision).where(
            PriceDecision.name_key == normalize_name(name),
            PriceDecision.row_type == row_type,
            PriceDecision.unit == (unit or "").strip().lower(),
        )
    )).scalar_one_or_none()
    if existing is None:
        return {"restored": False}

    await db.delete(existing)
    await db.commit()
    return {"restored": True}
