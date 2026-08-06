"""Сводимость единиц измерения: можно ли этой ценой оценивать эту позицию.

Цена всегда дана за какую-то единицу. Пока цену подбирали по одному названию,
цена за тонну спокойно вставала в строку с килограммами (×1000), а цена за
100 м2 — в строку с м2 (×100): название совпадало, единицу никто не смотрел.

Правило здесь одно и то же для всех источников цены — прайса, кеша прошлых
задач и ИИ:

* единицы совпали (с точностью до написания: «кв.м» = «м²») — цена как есть;
* единицы одной физической величины — цена пересчитывается точным
  коэффициентом (т → кг, «100 м2» → м2, л → м3);
* единицы разной природы — цену **не берём**. Сколько килограммов в мешке, мы
  не знаем, а выдуманное число хуже пустой ячейки;
* единица не указана хотя бы у одной стороны — берём как есть. Возражать нечем:
  отказ здесь выгнал бы в платный ИИ-поиск весь прайс без заполненных единиц.

Коэффициенты — константы справочника, каждый закреплён тестом с точным числом
(`backend/tests/test_unit_compat.py`). Меняете таблицу — меняйте тест.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from app.utils.unit_normalizer import unit_price_factor

# Что случилось при сверке единицы цены и единицы позиции.
STATUS_SAME = "same"                  # одна и та же единица
STATUS_CONVERTED = "converted"        # пересчитали коэффициентом
STATUS_UNKNOWN = "unknown"            # единица не указана — сверять нечего
STATUS_INCOMPATIBLE = "incompatible"  # разные величины — цена не подходит

# Пометки для человека. Пишутся в notes строки, по ним же редактор подсвечивает.
PRICE_CONVERTED_PREFIX = "Цена пересчитана"
PRICE_UNIT_MISMATCH_PREFIX = "Цена не подобрана: ед. изм. не совпадает"

# Физическая величина → {каноническая единица: размер в базовых единицах}.
#
# «пог.м» и «м» — одна и та же длина: в сметах это одно и то же, и отказ от
# цены из-за такого написания был бы ложной тревогой. «шт» и «ед» — тоже.
# А вот «компл», «мешок», «рулон» сюда не входят намеренно: сколько в них
# штук или килограммов — вопрос к человеку, а не к справочнику.
_DIMENSIONS: dict[str, dict[str, float]] = {
    "масса": {"г": 0.001, "кг": 1.0, "т": 1000.0},
    "длина": {"м": 1.0, "пог.м": 1.0},
    "площадь": {"м2": 1.0, "га": 10000.0},
    "объём": {"м3": 1.0, "л": 0.001},
    "штуки": {"шт": 1.0, "ед": 1.0},
}

_UNIT_TO_DIMENSION: dict[str, tuple[str, float]] = {
    unit: (dimension, size)
    for dimension, units in _DIMENSIONS.items()
    for unit, size in units.items()
}


def _measure(unit: Optional[str]) -> Optional[tuple[str, float]]:
    """Единица → (величина, размер в базовых единицах величины).

    «100 м2» → («площадь», 100). Незнакомая единица становится величиной сама
    по себе: «мешок» сводится только с «мешком».
    """
    base, prefix = unit_price_factor(unit)
    if not base:
        return None

    known = _UNIT_TO_DIMENSION.get(base)
    if known is not None:
        dimension, size = known
        return (dimension, size * prefix)

    # Незнакомую единицу не выдумываем, но сравнивать её с собой умеем:
    # написание гасим, чтобы «Мешок» и «мешок» не разъехались.
    return ("как есть:" + base.strip().lower().replace("ё", "е"), prefix)


def compare_units(
    price_unit: Optional[str],
    item_unit: Optional[str],
) -> tuple[str, Optional[float]]:
    """Сверить единицу цены с единицей позиции.

    Возвращает (статус, множитель к цене). Множитель None — цена не подходит.
    """
    if not str(price_unit or "").strip() or not str(item_unit or "").strip():
        return (STATUS_UNKNOWN, 1.0)

    price_measure = _measure(price_unit)
    item_measure = _measure(item_unit)
    if price_measure is None or item_measure is None:
        return (STATUS_UNKNOWN, 1.0)

    if price_measure[0] != item_measure[0]:
        return (STATUS_INCOMPATIBLE, None)
    if price_measure[1] == item_measure[1]:
        return (STATUS_SAME, 1.0)

    # Цена дана за price_unit, нужна за item_unit: во сколько раз item_unit
    # крупнее. Цена за тонну в позиции с кг → ×0,001.
    return (STATUS_CONVERTED, item_measure[1] / price_measure[1])


def _round_money(value: float) -> float:
    """До копеек. Совсем мелкую цену копейками не гасим: 4 ₽/т — это 0,004 ₽/кг,
    и округление превратило бы её в ноль, то есть в «цены нет»."""
    rounded = round(value, 2)
    if rounded == 0 and value != 0:
        return round(value, 6)
    return rounded


def convert_price(
    price: object,
    price_unit: Optional[str],
    item_unit: Optional[str],
) -> tuple[Optional[float], str]:
    """Цена за единицу позиции. None — цену брать нельзя (или её и не было)."""
    status, factor = compare_units(price_unit, item_unit)
    if factor is None:
        return (None, status)

    try:
        number = float(price)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return (None, status)

    if factor == 1.0:
        return (number, status)
    return (_round_money(number * factor), status)


def _fmt(value: float | int | Decimal) -> str:
    """Число для человека: 73.77 → «73,77», 73770 → «73770»."""
    decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    return format(decimal_value.normalize(), "f").replace(".", ",")


def converted_note(
    old_price: float,
    price_unit: Optional[str],
    new_price: float,
    item_unit: Optional[str],
    source: str,
) -> str:
    """Пометка о пересчёте. Молчаливое деление на 1000 пугает не меньше ошибки."""
    return (
        f"{PRICE_CONVERTED_PREFIX}: {_fmt(old_price)} ₽/{price_unit} → "
        f"{_fmt(new_price)} ₽/{item_unit} ({source})."
    )


def mismatch_note(
    price_unit: Optional[str],
    item_unit: Optional[str],
    source: str,
) -> str:
    """Пометка «цену не подобрали»: обе единицы названы, решает человек."""
    return (
        f"{PRICE_UNIT_MISMATCH_PREFIX} — {source}: «{price_unit}», "
        f"позиция: «{item_unit}»."
    )


def append_note(existing: Optional[str], addition: str) -> str:
    """Дописать пометку, не затирая прежние.

    Прежняя пометка остаётся первой: по её началу редактор подсвечивает строки
    комплектов материалов. Повторная проверка той же сметы пометку не двоит.
    """
    current = (existing or "").strip()
    if not current:
        return addition
    if addition in current:
        return current
    return f"{current}; {addition}"
