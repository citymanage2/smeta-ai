"""Сверка: что выдал ИИ, что из этого сделал сервис и что поправил человек.

План: plans/2026-09-10-sverka-i-obuchenie-na-pravkah.md, Фаза 2.

Три источника, каждый отвечает за свою колонку:

| Колонка | Откуда | Что означает |
|---|---|---|
| «ИИ выдал» | `ai_baselines.rows` — снимок до единой правки | ответ модели |
| «Сервис поставил» | `correction_signals.previous_value` первого касания | значение перед тем, как человек взялся за ячейку |
| «Сейчас» | строки документа | итог |

Зачем три, а не две. Между выдачей ИИ и правкой строку меняют операции, которые
человеком не являются: подбор цен по прайсу, проверка единиц, коэффициент,
оптимизация, миграция. Сигналов они не оставляют (и правильно делают — это не
ошибки человека). Поэтому «ИИ выдал 3000, сейчас 2500» само по себе не говорит,
кто поменял: может, человек, а может, прайс. Различает их журнал: есть сигнал на
ячейку — менял человек, нет — менял сервис.

Само сопоставление строк не изобретается заново: его делает
`document_service.diff_rows`, тот же код, которым считаются правки и который
кладёт рядом машинный ключ поля. Иначе сверка и журнал разошлись бы в том, что
считать изменением, — и разошлись бы молча.
"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_baseline import AiBaseline
from app.models.correction_signal import FIELD_ROW, CorrectionSignal
from app.services import ai_baseline as baseline_service
from app.utils.estimate_rows import row_cost
from app.utils.price_coercion import coerce_price, coerce_qty

# Потолок строк в ответе. Сверка — инструмент разбора, а не выгрузка: тысяча
# расхождений не читается человеком и не помещается в панель. Превышение видно
# в `truncated`, а не съедается молча.
MAX_RECON_ROWS = 300

# Кто изменил ячейку после ИИ.
BY_HUMAN = "human"
BY_SERVICE = "service"

# Что случилось со строкой целиком.
ROW_CHANGED = "changed"
ROW_ADDED = "added"
ROW_REMOVED = "removed"


def _num(value: Any) -> Optional[float]:
    """Число из значения ячейки; нечисловое — None (сравнивать будем как текст)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(str(value).strip().replace(",", ".").replace(" ", ""))
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _rows_total(rows: list, row_format: str) -> Optional[float]:
    """Стоимость набора строк. Для перечня и полноты — None.

    Считается ровно тем же `row_cost`, что и стоимость строки сметы в остальном
    проекте: отдельная формула здесь означала бы, что «промах» на этом экране не
    сходится с итогом редактора. У generic-строк (перечень, полнота) колонки
    произвольные, надёжной формулы стоимости нет — и выдумывать её нельзя.
    """
    if row_format != "estimate":
        return None
    total = 0.0
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        cost = row_cost(
            coerce_qty(row.get("qty")),
            coerce_price(row.get("price_work")),
            coerce_price(row.get("price_material")),
        )
        if cost:
            total += cost
    return round(total, 2)


async def _first_touch_map(
    db: AsyncSession, task_id: str, document_kind: str
) -> dict[tuple, CorrectionSignal]:
    """Первые касания ячеек: `(row_key, field)` → сигнал.

    Только `is_first_touch`: вторая правка той же ячейки — разговор человека с
    самим собой, и её `previous_value` это уже человеческое число, а не то, что
    поставил сервис.
    """
    result = await db.execute(
        select(CorrectionSignal).where(
            CorrectionSignal.task_id == task_id,
            CorrectionSignal.document_kind == document_kind,
            CorrectionSignal.is_first_touch.is_(True),
        )
    )
    return {(s.row_key, s.field): s for s in result.scalars().all()}


def _build_cell(
    change: dict,
    signal: Optional[CorrectionSignal],
) -> dict:
    """Одна изменившаяся ячейка в трёх колонках."""
    ai_value = change.get("previous")
    current_value = change.get("new")

    if signal is not None:
        # Человек правил эту ячейку. Значение перед его правкой — то, что
        # оставил сервис; оно может отличаться от ответа ИИ, если между ними
        # отработал подбор цен или проверка единиц.
        service_value = signal.previous_value
        changed_by = BY_HUMAN
    else:
        # Сигнала нет — значит ячейку правил не человек. «Сервис поставил» и
        # «сейчас» это одно и то же число.
        service_value = current_value
        changed_by = BY_SERVICE

    ai_num = _num(ai_value)
    current_num = _num(current_value)
    delta = None
    delta_pct = None
    if ai_num is not None and current_num is not None:
        delta = round(current_num - ai_num, 4)
        # Процент считается только когда есть от чего считать. Ноль в
        # знаменателе — не «бесконечный промах», а отсутствие базы сравнения.
        if ai_num:
            delta_pct = round((current_num - ai_num) / abs(ai_num) * 100, 2)

    return {
        "field": change.get("field"),
        "field_key": change.get("field_key"),
        "ai_value": _text(ai_value),
        "service_value": _text(service_value),
        "current_value": _text(current_value),
        "changed_by": changed_by,
        "delta": delta,
        "delta_pct": delta_pct,
        "price_source": signal.price_source if signal is not None else None,
        "user_name": signal.user_name if signal is not None else None,
    }


async def build(
    db: AsyncSession,
    *,
    task_id: str,
    document_kind: str,
    row_format: str,
    current_rows: list,
) -> dict:
    """Сверка документа. Снимка нет — честно говорим об этом и не выдумываем."""
    from app.services.document_service import diff_rows

    snapshot: Optional[AiBaseline] = await baseline_service.read(
        db, task_id=task_id, document_kind=document_kind
    )
    if snapshot is None:
        return {
            "has_baseline": False,
            "baseline_truncated": False,
            "baseline_row_count": 0,
            "rows": [],
            "truncated": False,
            "totals": {
                "ai_total": None,
                "current_total": _rows_total(current_rows, row_format),
                "delta": None,
                "delta_pct": None,
            },
            "counts": {"changed": 0, "added": 0, "removed": 0,
                       "by_human": 0, "by_service": 0},
        }

    baseline_rows = snapshot.rows or []
    changes = diff_rows(baseline_rows, current_rows or [], row_format)
    signals = await _first_touch_map(db, task_id, document_kind)

    # Группируем по строке: человеку читать построчно, а не поячеечно.
    grouped: dict[str, dict] = {}
    order: list[str] = []
    counts = {"changed": 0, "added": 0, "removed": 0, "by_human": 0, "by_service": 0}

    for change in changes:
        row_key = change.get("row_key")
        if row_key is None:
            continue
        field_key = change.get("field_key")
        signal = signals.get((row_key, field_key))

        if row_key not in grouped:
            grouped[row_key] = {
                "row_key": row_key,
                "row_number": change.get("row_number"),
                "row_name": change.get("row_name") or "",
                "status": ROW_CHANGED,
                "cells": [],
            }
            order.append(row_key)

        entry = grouped[row_key]

        if field_key == FIELD_ROW:
            # Строку добавили или удалили целиком — самый ценный сигнал:
            # система пропустила позицию или выдумала лишнюю.
            added = str(change.get("new") or "") == "добавлена"
            entry["status"] = ROW_ADDED if added else ROW_REMOVED
            entry["changed_by"] = BY_HUMAN if signal is not None else BY_SERVICE
            counts["added" if added else "removed"] += 1
            counts["by_human" if signal is not None else "by_service"] += 1
            continue

        cell = _build_cell(change, signal)
        entry["cells"].append(cell)
        counts["by_human" if signal is not None else "by_service"] += 1

    rows = [grouped[key] for key in order]
    # Строка, у которой изменений не нашлось, в список не попадает вовсе:
    # «совпало» — это отсутствие строки, а не пустая строка в таблице.
    rows = [r for r in rows if r["cells"] or r["status"] != ROW_CHANGED]
    counts["changed"] = sum(1 for r in rows if r["status"] == ROW_CHANGED)

    truncated = len(rows) > MAX_RECON_ROWS
    if truncated:
        rows = rows[:MAX_RECON_ROWS]

    ai_total = _rows_total(baseline_rows, row_format)
    current_total = _rows_total(current_rows, row_format)
    delta = None
    delta_pct = None
    if ai_total is not None and current_total is not None:
        delta = round(current_total - ai_total, 2)
        if ai_total:
            delta_pct = round((current_total - ai_total) / abs(ai_total) * 100, 2)

    return {
        "has_baseline": True,
        "baseline_truncated": bool(snapshot.truncated),
        "baseline_row_count": snapshot.row_count,
        "rows": rows,
        "truncated": truncated,
        "totals": {
            "ai_total": ai_total,
            "current_total": current_total,
            "delta": delta,
            "delta_pct": delta_pct,
        },
        "counts": counts,
    }
