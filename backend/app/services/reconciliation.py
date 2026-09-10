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

# Чем сопоставлены строки снимка и документа.
MATCH_ROW_ID = "row_id"       # по идентификатору строки — обычный случай
MATCH_NAME_UNIT = "name_unit"  # идентификаторы разошлись, сверяем по имени
MATCH_NONE = "none"            # сверять нечем

# Ниже этой доли общих идентификаторов считаем, что они разошлись. Так бывает
# после миграции смет: `estimate_migration` пересобирает строки из позиций без
# `row_id`, и `item_to_row` выдаёт каждой новый uuid. Сравнение по id тогда
# показало бы «ИИ выдал N позиций, все удалены, человек добавил N» — то есть
# полную чушь вместо расхождений.
MIN_ID_OVERLAP = 0.5

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


def _is_section(row: dict) -> bool:
    return str(row.get("type") or "").strip().lower() in ("section", "раздел")


def _rows_total(
    rows: list, row_format: str, overhead_pct: float, transport_pct: float
) -> Optional[float]:
    """ИТОГО набора строк. Для перечня и полноты — None.

    Формула обязана совпадать с той, что видит человек в редакторе
    (`frontend/src/utils/estimateCalc.ts`) и что уходит в файл, иначе «промах»
    на этом экране не сойдётся с итогом сметы — а правило 4 CLAUDE.md требует
    одной формулы на экран и файл:

        ИТОГО = работы + работы×%накладных + материалы + материалы×%транспортных

    Отсюда же три исключения, которые легко забыть: исключённые строки, разделы
    (у них своей стоимости нет) и строки-вычеты — у последних `coerce_qty`
    обнуляет отрицательный объём, зеркально `billableQty` на экране.

    У generic-строк (перечень, полнота) колонки произвольные, надёжной формулы
    стоимости нет — выдумывать её нельзя.
    """
    if row_format != "estimate":
        return None

    sum_work = 0.0
    sum_material = 0.0
    for row in rows or []:
        if not isinstance(row, dict) or row.get("is_excluded") or _is_section(row):
            continue
        qty = coerce_qty(row.get("qty"))
        work = row_cost(qty, coerce_price(row.get("price_work")), None)
        material = row_cost(qty, None, coerce_price(row.get("price_material")))
        sum_work += work or 0.0
        sum_material += material or 0.0

    grand = (
        sum_work + sum_work * overhead_pct / 100
        + sum_material + sum_material * transport_pct / 100
    )
    return round(grand, 2)


def _row_ids(rows: list) -> set:
    ids = set()
    for row in rows or []:
        if isinstance(row, dict):
            key = row.get("row_id") or row.get("id")
            if key:
                ids.add(str(key))
    return ids


def _name_unit_key(row: Any, row_format: str) -> Optional[str]:
    """Ключ «та же позиция» на случай, когда идентификаторы разошлись."""
    from app.services.document_service import _row_name

    if not isinstance(row, dict):
        return None
    name = " ".join(str(_row_name(row, row_format) or "").lower().split())
    if not name:
        return None
    if row_format == "generic":
        cells = row.get("cells") or {}
        unit = ""
        for key, value in cells.items():
            squashed = "".join(ch for ch in str(key).lower() if ch.isalnum())
            if squashed in ("едизм", "единица", "единицаизмерения", "ед"):
                unit = str(value or "").strip().lower()
                break
    else:
        unit = str(row.get("unit") or "").strip().lower()
    return f"{name}|{unit}"


def _realign_by_name(baseline_rows: list, current_rows: list, row_format: str) -> list:
    """Переписать идентификаторы снимка под текущие строки по имени и единице.

    Неоднозначное совпадение (имя встречается в документе больше одного раза) не
    берётся вовсе: выдуманная пара хуже пустой ячейки — то же правило, что у
    номеров позиций (правило 7 CLAUDE.md).
    """
    buckets: dict[str, list] = {}
    for row in current_rows or []:
        key = _name_unit_key(row, row_format)
        if key:
            buckets.setdefault(key, []).append(row)

    realigned = []
    for row in baseline_rows or []:
        if not isinstance(row, dict):
            continue
        key = _name_unit_key(row, row_format)
        matches = buckets.get(key or "", [])
        if len(matches) != 1:
            realigned.append(row)
            continue
        target = matches[0]
        new_id = target.get("row_id") or target.get("id")
        if not new_id:
            realigned.append(row)
            continue
        copy_row = dict(row)
        if "row_id" in copy_row or row_format == "generic":
            copy_row["row_id"] = str(new_id)
        else:
            copy_row["id"] = str(new_id)
        realigned.append(copy_row)
    return realigned


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
        # …но после человека ячейку мог изменить и сам сервис: проверка единиц,
        # откат, оптимизация. Тогда текущее значение — машинное, и подписывать
        # его человеком нельзя: он такого не ставил.
        if _text(signal.new_value) != _text(current_value):
            changed_by = BY_SERVICE
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
    overhead_pct: float = 0.0,
    transport_pct: float = 0.0,
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
            "ai_row_count": 0,
            "compared_row_count": 0,
            "match_mode": MATCH_NONE,
            "rows": [],
            "truncated": False,
            "totals": {
                "ai_total": None,
                "current_total": _rows_total(
                    current_rows, row_format, overhead_pct, transport_pct
                ),
                "delta": None,
                "delta_pct": None,
            },
            "counts": {"rows_changed": 0, "rows_added": 0, "rows_removed": 0,
                       "cells_by_human": 0, "cells_by_service": 0},
        }

    baseline_rows = snapshot.rows or []
    current = current_rows or []

    # Сопоставлять по идентификаторам можно, только если они те же. После
    # миграции смет (`estimate_migration`) строки пересобираются из позиций без
    # `row_id`, и каждая получает новый uuid — сравнение по id показало бы, что
    # человек удалил все позиции ИИ и завёл столько же своих.
    baseline_ids = _row_ids(baseline_rows)
    current_ids = _row_ids(current)
    common = baseline_ids & current_ids
    smaller = min(len(baseline_ids), len(current_ids)) or 1
    match_mode = MATCH_ROW_ID
    if len(common) / smaller < MIN_ID_OVERLAP:
        baseline_rows = _realign_by_name(baseline_rows, current, row_format)
        match_mode = (
            MATCH_NAME_UNIT
            if _row_ids(baseline_rows) & current_ids
            else MATCH_NONE
        )

    changes = diff_rows(baseline_rows, current, row_format)
    signals = await _first_touch_map(db, task_id, document_kind)

    # Группируем по строке: человеку читать построчно, а не поячеечно.
    grouped: dict[str, dict] = {}
    order: list[str] = []
    # Строки и ячейки считаются отдельно: смешивать их в одном счётчике значит
    # показать человеку два разных числа под одной подписью.
    counts = {"rows_changed": 0, "rows_added": 0, "rows_removed": 0,
              "cells_by_human": 0, "cells_by_service": 0}

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
            counts["rows_added" if added else "rows_removed"] += 1
            continue

        cell = _build_cell(change, signal)
        entry["cells"].append(cell)
        counts[
            "cells_by_human" if cell["changed_by"] == BY_HUMAN else "cells_by_service"
        ] += 1

    rows = [grouped[key] for key in order]
    # Строка, у которой изменений не нашлось, в список не попадает вовсе:
    # «совпало» — это отсутствие строки, а не пустая строка в таблице.
    rows = [r for r in rows if r["cells"] or r["status"] != ROW_CHANGED]
    counts["rows_changed"] = sum(1 for r in rows if r["status"] == ROW_CHANGED)

    truncated = len(rows) > MAX_RECON_ROWS
    if truncated:
        rows = rows[:MAX_RECON_ROWS]

    ai_total = _rows_total(baseline_rows, row_format, overhead_pct, transport_pct)
    current_total = _rows_total(current, row_format, overhead_pct, transport_pct)
    delta = None
    delta_pct = None
    if ai_total is not None and current_total is not None:
        delta = round(current_total - ai_total, 2)
        if ai_total:
            delta_pct = round((current_total - ai_total) / abs(ai_total) * 100, 2)

    return {
        "has_baseline": True,
        "baseline_truncated": bool(snapshot.truncated),
        # Сколько строк выдал ИИ и сколько из них реально сверено: у усечённого
        # снимка это разные числа, и выдавать первое за второе нельзя.
        "ai_row_count": snapshot.row_count,
        "compared_row_count": len(baseline_rows),
        "match_mode": match_mode,
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
