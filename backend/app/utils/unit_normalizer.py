from __future__ import annotations

import re
from typing import Optional

_PREFIX_SPACE_RE = re.compile(r'^(\d+(?:[.,]\d+)?)\s+(.+)$')
_PREFIX_NOSPACE_RE = re.compile(r'^(\d+(?:[.,]\d+)?)([а-яёА-ЯЁa-zA-Z].+)$')

_KNOWN_UNITS = {
    "м", "м2", "м3", "т", "кг", "шт", "пог.м", "п.м",
    "чел.-час", "чел-час", "маш.-ч", "маш-ч", "т·км", "л",
    "компл", "компл.", "га", "пм", "м пог", "ед",
}

# ---------------------------------------------------------------------------
# Единое написание единицы измерения
# ---------------------------------------------------------------------------
#
# Одну и ту же единицу пишут по-разному: «м2», «м²», «кв.м», «кв. м». Для
# человека это одно и то же, для прайса — четыре разные позиции, и цены по ним
# разъезжаются. Поэтому при записи в прайс единица приводится к одному виду.
#
# Ключ словаря — «сжатое» написание (без пробелов, точек, дефисов и косых),
# значение — то, как единица пишется в прайсе.

_SQUEEZE_RE = re.compile(r'[\s.\-/\\]+')

_UNIT_ALIASES = {
    "м2": "м2", "квм": "м2", "мкв": "м2", "квметр": "м2", "квметров": "м2", "m2": "м2",
    "м3": "м3", "кубм": "м3", "мкуб": "м3", "кубметр": "м3", "m3": "м3",
    "м": "м", "метр": "м", "метров": "м", "m": "м",
    "погм": "пог.м", "пм": "пог.м", "мп": "пог.м", "погонныйметр": "пог.м",
    "шт": "шт", "штук": "шт", "штука": "шт", "штуки": "шт", "pcs": "шт",
    "кг": "кг", "килограмм": "кг", "kg": "кг",
    "т": "т", "тонна": "т", "тонн": "т",
    "г": "г", "грамм": "г",
    "л": "л", "литр": "л", "литров": "л",
    "компл": "компл", "комплект": "компл", "комплектов": "компл",
    "челчас": "чел.-час", "человекочас": "чел.-час",
    "машч": "маш.-ч", "машиночас": "маш.-ч",
    "га": "га", "гектар": "га",
    "ед": "ед", "единица": "ед",
    "тыс": "тыс", "%": "%",
}

_CANONICAL_UNITS = set(_UNIT_ALIASES.values())


def _squeeze(unit: str) -> str:
    """Сжать написание до сравнимого вида: «кв. м» и «м.кв.» → «квм» и «мкв»."""
    text = unit.strip().lower().replace("ё", "е")
    text = text.replace("²", "2").replace("³", "3")
    return _SQUEEZE_RE.sub("", text)


def canonical_unit(unit: Optional[str]) -> str:
    """Привести единицу измерения к единому написанию.

    Незнакомую единицу не выдумываем — возвращаем как написал человек, только
    без лишних пробелов: лучше оставить «бухту» бухтой, чем угадать неверно.
    """
    if not unit:
        return ""
    squeezed = _squeeze(str(unit))
    if not squeezed:
        return ""
    return _UNIT_ALIASES.get(squeezed, str(unit).strip())


def unit_price_factor(unit: Optional[str]) -> "tuple[str, float]":
    """Единица с множителем → (единица, во сколько раз цена больше базовой).

    «100 м2» по 5000 ₽ — это 50 ₽ за м2. Без пересчёта прайс завысил бы цену в
    сто раз, и все будущие сметы считались бы по ней.
    """
    if not unit:
        return ("", 1.0)

    text = str(unit).strip()
    match = _PREFIX_SPACE_RE.match(text) or _PREFIX_NOSPACE_RE.match(text)
    if match:
        base = canonical_unit(match.group(2))
        try:
            prefix = float(match.group(1).replace(",", "."))
        except ValueError:
            prefix = 0.0
        # Множитель применяем только к понятной единице: «2 слоя» — это не
        # «2 × слой», а название единицы, и делить цену на 2 там нельзя.
        if prefix > 0 and base in _CANONICAL_UNITS:
            return (base, prefix)

    return (canonical_unit(text), 1.0)


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
