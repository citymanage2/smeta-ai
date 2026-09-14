"""Цены КП: приведение и выбор лучшей цены позиции.

План: plans/2026-09-14-zapros-kp.md, фаза 4. **Единственное место**, где цена
из КП приводится к виду сметы и прайса: без НДС и за единицу позиции запроса.
Сравнительная таблица, запись в прайс (фаза 7) и цены в оптимизацию (фаза 8)
зовут эти функции, а не пересчитывают сами — иначе одна и та же цена КП
получила бы на экране одно число, а в прайсе другое.

Правила:

* **Порядок: НДС → единица → одно округление.** Округлив до копеек после НДС,
  цену за кг в позиции «т» умножили бы на 1000 вместе с ошибкой округления.
  Считаем в `Decimal`, округляем один раз в конце.
* **НДС:** «с НДС» → цена ÷ (1 + ставка/100), ставка по умолчанию 22 %;
  «без НДС» → как есть.
* **Единица** — правило №8 и `unit_compat`: совпала или не указана — как есть,
  сводится — точный коэффициент, не сводится (мешок ↔ кг) — приведённой цены
  нет, причина в ячейке, в минимуме цена не участвует.
* **Черновик в минимуме не участвует.** Цена от ИИ — черновик, пока человек её
  не подтвердил (критерий 18); сравнивать непроверенное число нельзя.
* **Выбор человека перекрывает минимум**, но только если у выбранного КП есть
  подтверждённая приведённая цена; иначе — минимум (выбор не теряется, он
  просто пока нечем подкрепить).
* **«Включает материалы»** у цены перекрывает отметку КП; `NULL` — как у КП.

Приведённая цена не хранится (как отклонение от цели сводной, правило №16):
любая правка цены, единицы, НДС или единицы позиции сразу меняет результат.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Iterable, Optional

from app.utils.unit_compat import STATUS_INCOMPATIBLE, compare_units

VAT_WITH = "with_vat"
VAT_WITHOUT = "without_vat"
VAT_MODES = (VAT_WITH, VAT_WITHOUT)
DEFAULT_VAT_RATE = 22

_CENT = Decimal("0.01")
_MICRO = Decimal("0.000001")


def _decimal(value: Any) -> Optional[Decimal]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def net_price(price: Any, vat_mode: Optional[str], vat_rate: Any) -> Optional[Decimal]:
    """Цена без НДС, **без округления**. None — числа нет."""
    number = _decimal(price)
    if number is None:
        return None
    if vat_mode != VAT_WITH:
        return number
    rate = _decimal(vat_rate)
    if rate is None:
        rate = Decimal(DEFAULT_VAT_RATE)
    return number / (Decimal(1) + rate / Decimal(100))


def round_money(value: Decimal) -> float:
    """До копеек. Совсем мелкую цену копейками не гасим (как `unit_compat`):
    4 ₽/т — это 0,004 ₽/кг, а не «цены нет»."""
    rounded = value.quantize(_CENT, rounding=ROUND_HALF_UP)
    if rounded == 0 and value != 0:
        rounded = value.quantize(_MICRO, rounding=ROUND_HALF_UP)
    return float(rounded)


def incompatible_reason(price_unit: Optional[str], item_unit: Optional[str]) -> str:
    return (
        f"Ед. изм. КП «{price_unit}» не сводится с ед. изм. позиции «{item_unit}» — "
        "цена не участвует в сравнении"
    )


def normalized(
    price: Any,
    price_unit: Optional[str],
    item_unit: Optional[str],
    vat_mode: Optional[str],
    vat_rate: Any,
) -> tuple[Optional[float], str, Optional[str]]:
    """Приведённая цена: без НДС, за единицу позиции, округлена один раз.

    Возвращает (цена | None, статус сверки единиц, причина отказа | None).
    """
    status, factor = compare_units(price_unit, item_unit)
    if factor is None:
        return (None, status, incompatible_reason(price_unit, item_unit))
    net = net_price(price, vat_mode, vat_rate)
    if net is None:
        return (None, status, None)
    if factor != 1.0:
        net = net * Decimal(repr(factor))
    return (round_money(net), status, None)


def effective_includes_materials(price_row: Any, offer: Any) -> bool:
    own = getattr(price_row, "includes_materials", None)
    if own is not None:
        return bool(own)
    return bool(getattr(offer, "includes_materials", False))


def cell(item: Any, offer: Any, price_row: Any) -> dict:
    """Ячейка матрицы «позиция × КП»."""
    base = {
        "offer_id": str(offer.id),
        "price": None, "unit": None, "name_in_offer": None,
        "source": None, "confidence": None, "confirmed": None,
        "includes_materials": bool(getattr(offer, "includes_materials", False)),
        "normalized_price": None, "unit_status": None, "reason": None,
    }
    if price_row is None:
        return base
    value, unit_status, reason = normalized(
        price_row.price, price_row.unit, item.unit, offer.vat_mode, offer.vat_rate,
    )
    base.update({
        "price": price_row.price,
        "unit": price_row.unit,
        "name_in_offer": price_row.name_in_offer,
        "source": price_row.source,
        "confidence": price_row.confidence,
        "confirmed": bool(price_row.confirmed),
        "includes_materials": effective_includes_materials(price_row, offer),
        "normalized_price": value,
        "unit_status": unit_status,
        "reason": reason,
    })
    return base


def _candidates(item: Any, offers: list, prices: Iterable[Any]) -> list[tuple[Any, Any, float]]:
    """(КП, цена, приведённая) — только подтверждённые и приведённые, в порядке КП."""
    by_offer = {str(p.offer_id): p for p in prices}
    out = []
    for offer in offers:
        row = by_offer.get(str(offer.id))
        if row is None or not row.confirmed:
            continue
        value, _status, _reason = normalized(row.price, row.unit, item.unit, offer.vat_mode, offer.vat_rate)
        if value is None:
            continue
        out.append((offer, row, value))
    return out


def best_for_item(item: Any, offers: list, prices: Iterable[Any]) -> Optional[dict]:
    """Итоговая цена позиции: выбранное КП, иначе минимум. None — цены нет.

    `offers` — КП запроса в порядке загрузки (при равных ценах берётся раньше
    загруженное), `prices` — цены этой позиции.
    """
    candidates = _candidates(item, offers, prices)
    if not candidates:
        return None
    selected_id = str(item.selected_offer_id) if item.selected_offer_id else None
    chosen = next((c for c in candidates if str(c[0].id) == selected_id), None)
    is_selected = chosen is not None
    if chosen is None:
        chosen = min(candidates, key=lambda c: c[2])  # min стабилен: первый из равных
    offer, row, value = chosen
    return {
        "offer_id": str(offer.id),
        "supplier_name": offer.supplier_name,
        "offer_date": offer.offer_date,
        "price": value,
        "includes_materials": effective_includes_materials(row, offer),
        "selected": is_selected,
        "offers_count": len(candidates),
    }


def item_matrix(item: Any, offers: list, prices: Iterable[Any]) -> dict:
    """Строка сравнительной таблицы: ячейки по КП, минимум и итоговая цена."""
    prices = list(prices)
    by_offer = {str(p.offer_id): p for p in prices}
    candidates = _candidates(item, offers, prices)
    minimum = min(candidates, key=lambda c: c[2]) if candidates else None
    return {
        "cells": [cell(item, offer, by_offer.get(str(offer.id))) for offer in offers],
        "min_offer_id": str(minimum[0].id) if minimum else None,
        "best": best_for_item(item, offers, prices),
    }
