"""Перевод сметы между двумя историческими форматами строк.

Смета в проекте существует в двух видах:

* **позиция ИИ** (`item`) — то, что выдаёт расчёт и что понимает генератор xlsx:
  `{type: "Работа"|"Материал", name, unit, quantity, work_price, material_price,
    price_list_name, sources, notes}`;
* **строка документа** (`row`, `EstimateRowSchema`) — то, с чем работает редактор:
  `{id, lineage_id, num, type: "work"|"material"|"section", name, unit, qty,
    price_work, price_material, cost, ...}`.

Единым источником правды становится строка документа (план 2026-08-02, Фаза 5),
но генератор xlsx и подбор цен через ИИ говорят на языке позиций. Этот модуль —
единственное место перевода, чтобы правило «стоимость = объём × цена» и правила
приведения цен не разъехались по трём копиям.

Перевод обратим: `rows_to_items` кладёт в позицию `row_id`, и `items_to_rows`
по нему восстанавливает ту же строку. Без этого подбор цен пересоздавал бы
строки с новыми идентификаторами — и терялись бы история правок и связь
материала с работой.
"""
from __future__ import annotations

import uuid as _uuid
from typing import Any, Optional

from app.utils.price_coercion import coerce_price, coerce_qty, coerce_qty_signed

# Поля позиции, которые нужны генератору xlsx и показываются человеку, но не
# входят в схему строки. Переносим как есть, чтобы источник цены и найденные
# ссылки не пропадали при первом же сохранении из редактора.
#
# `sheet` — лист исходного файла, если он был разбит на несколько. Он же
# вкладка в редакторе и лист в скачиваемом файле, поэтому терять его при
# переводе позиция↔строка нельзя: смета собралась бы в один лист.
PASSTHROUGH_FIELDS = ("price_list_name", "sources", "notes", "sheet")

_LABEL_TO_TYPE = {
    "работа": "work", "работы": "work", "work": "work",
    "материал": "material", "материалы": "material", "material": "material",
    "раздел": "section", "section": "section",
}
_TYPE_TO_LABEL = {"work": "Работа", "material": "Материал", "section": "Раздел"}


def _row_type(raw_type: Any, work_price: Optional[float], material_price: Optional[float]) -> str:
    key = str(raw_type or "").strip().lower()
    if key in _LABEL_TO_TYPE:
        return _LABEL_TO_TYPE[key]
    # Тип не указан — определяем по тому, какая цена заполнена. Совпадает с
    # логикой разбора чужой сметы (`estimate_parser._infer_type`).
    if material_price is not None and work_price is None:
        return "material"
    return "work"


def row_cost(qty: Any, price_work: Optional[float], price_material: Optional[float]) -> Optional[float]:
    """Стоимость строки — ровно так же, как её считает генератор xlsx.

    `coerce_qty` обнуляет отрицательный объём: строка-вычет корректирует объём
    соседней позиции и собственной стоимости не имеет.
    """
    billable = coerce_qty(qty)
    work = round(billable * price_work, 2) if price_work is not None and billable else None
    material = round(billable * price_material, 2) if price_material is not None and billable else None
    if work is None and material is None:
        return None
    return round((work or 0.0) + (material or 0.0), 2)


def item_to_row(item: dict, num: Optional[int] = None) -> dict:
    """Позиция ИИ → строка документа."""
    work_price = coerce_price(item.get("work_price"))
    material_price = coerce_price(item.get("material_price"))
    qty = coerce_qty_signed(item.get("quantity"))

    row_id = str(item.get("row_id") or _uuid.uuid4())
    lineage_id = str(item.get("lineage_id") or row_id)

    row = {
        "id": row_id,
        "lineage_id": lineage_id,
        "num": num,
        "type": _row_type(item.get("type"), work_price, material_price),
        "name": str(item.get("name") or "").strip(),
        "unit": str(item.get("unit") or ""),
        "qty": qty,
        "price_work": work_price,
        "price_material": material_price,
        "cost": row_cost(qty, work_price, material_price),
        "selected": False,
        "abc_group": None,
        "optimization_note": None,
    }
    for field in PASSTHROUGH_FIELDS:
        value = item.get(field)
        row[field] = value if value not in ("", None) else None
    return row


def items_to_rows(items: list) -> list[dict]:
    return [
        item_to_row(item, num=index + 1)
        for index, item in enumerate(items or [])
        if isinstance(item, dict)
    ]


def row_to_item(row: dict) -> dict:
    """Строка документа → позиция ИИ.

    `row_id` кладём в позицию намеренно: генератор xlsx лишние ключи игнорирует,
    а обратный перевод по нему сохраняет идентичность строки.
    """
    row_type = str(row.get("type") or "work").strip().lower()
    row_type = _LABEL_TO_TYPE.get(row_type, row_type)

    item = {
        "row_id": str(row.get("id") or ""),
        "lineage_id": str(row.get("lineage_id") or row.get("id") or ""),
        "type": _TYPE_TO_LABEL.get(row_type, "Работа"),
        "name": str(row.get("name") or ""),
        "unit": str(row.get("unit") or ""),
        "quantity": row.get("qty"),
        "work_price": coerce_price(row.get("price_work")),
        "material_price": coerce_price(row.get("price_material")),
    }
    for field in PASSTHROUGH_FIELDS:
        item[field] = row.get(field)
    return item


def rows_to_items(rows: list) -> list[dict]:
    return [row_to_item(row) for row in (rows or []) if isinstance(row, dict)]


def items_total(items: list) -> float:
    """Итог сметы по позициям — та же формула, что в скачиваемом файле.

    Нужна там, где строить целый xlsx ради одного числа расточительно (отчёт
    миграции по всем сметам). Совпадение с генератором закреплено тестом.
    """
    works = 0.0
    materials = 0.0
    for item in items or []:
        if not isinstance(item, dict):
            continue
        qty = coerce_qty(item.get("quantity"))
        work_price = coerce_price(item.get("work_price"))
        material_price = coerce_price(item.get("material_price"))
        if work_price is not None and qty:
            works += round(qty * work_price, 2)
        if material_price is not None and qty:
            materials += round(qty * material_price, 2)
    return round(works + round(works * 0.03, 2) + materials + round(materials * 0.03, 2), 2)


def items_signature(items: list) -> list[tuple]:
    """Сравнимый слепок сметы: только то, что влияет на цифры и на файл.

    Нужен, чтобы отличить «две копии сметы разошлись» от «отличаются
    идентификаторы строк и порядок ключей». Идентификаторы, номера строк и
    служебные поля в слепок не входят.
    """
    signature = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        signature.append((
            str(item.get("type") or ""),
            str(item.get("name") or "").strip(),
            str(item.get("unit") or "").strip(),
            coerce_qty_signed(item.get("quantity")),
            coerce_price(item.get("work_price")),
            coerce_price(item.get("material_price")),
        ))
    return signature
