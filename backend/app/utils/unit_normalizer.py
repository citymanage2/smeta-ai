from __future__ import annotations

import re

_PREFIX_SPACE_RE = re.compile(r'^(\d+(?:[.,]\d+)?)\s+(.+)$')
_PREFIX_NOSPACE_RE = re.compile(r'^(\d+(?:[.,]\d+)?)([а-яёА-ЯЁa-zA-Z].+)$')

_KNOWN_UNITS = {
    "м", "м2", "м3", "т", "кг", "шт", "пог.м", "п.м",
    "чел.-час", "чел-час", "маш.-ч", "маш-ч", "т·км", "л",
    "компл", "компл.", "га", "пм", "м пог", "ед",
}


def normalize_unit_quantity(
    unit: str | None,
    quantity: float | None,
) -> tuple[str, float | None, bool]:
    """
    Возвращает (new_unit, new_quantity, was_changed).
    Пример: ("100 м2", 0.1) → ("м2", 10.0, True)
    """
    if not unit:
        return (unit or "", quantity, False)

    s = unit.strip()

    m = _PREFIX_SPACE_RE.match(s) or _PREFIX_NOSPACE_RE.match(s)
    if not m:
        return (unit, quantity, False)

    prefix_str = m.group(1).replace(',', '.')
    base_unit = m.group(2).strip()

    if not base_unit or base_unit not in _KNOWN_UNITS:
        return (unit, quantity, False)

    prefix = float(prefix_str)
    if prefix <= 0:
        return (unit, quantity, False)
    if prefix == 1.0:
        return (base_unit, quantity, True)

    if quantity is None:
        return (base_unit, None, True)
    try:
        qty_float = float(quantity)
    except (TypeError, ValueError):
        return (unit, quantity, False)
    new_qty = round(qty_float * prefix, 6)
    return (base_unit, new_qty, True)


def normalize_items(items: list[dict]) -> list[dict]:
    """
    Применяет нормализацию ко всем позициям списка.
    При изменении дописывает в notes информацию о конвертации.
    """
    result = []
    for item in items:
        new_item = dict(item)
        unit = item.get("unit") or ""
        qty = item.get("quantity")
        new_unit, new_qty, changed = normalize_unit_quantity(unit, qty)
        if changed:
            new_item["unit"] = new_unit
            new_item["quantity"] = new_qty
            note_suffix = f"Ед. изм. нормализована: {unit} → {new_unit}"
            existing = (item.get("notes") or "").strip()
            new_item["notes"] = f"{existing}; {note_suffix}" if existing else note_suffix
        result.append(new_item)
    return result
