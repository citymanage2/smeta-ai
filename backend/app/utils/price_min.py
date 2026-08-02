"""Какая цена работы попадает в расчёт сметы.

У работы в прайсе несколько цен: по одной на подрядчика плюс цена, добавленная
из сметы (псевдо-подрядчик «Из смет»). В расчёт идёт `min_price` — одно число,
и правило его выбора должно быть одинаковым везде, где прайс пишется: при
пакетном добавлении из редактора, при ручной правке каталога и при загрузке
прайса файлом. Иначе одна и та же работа получала бы разную цену в зависимости
от того, каким путём её последний раз тронули.

**Решение пользователя (2026-08-03): приоритет у цены из смет.** Если она есть —
берём её. Цены подрядчиков работают, только когда цены из смет нет.
"""
from typing import Optional

# Псевдо-подрядчик: под этим именем в прайс попадают цены из смет. Отдельное имя
# нужно, чтобы такие цены не смешивались с настоящими прайсами подрядчиков и их
# было видно в каталоге.
ESTIMATE_CONTRACTOR = "Из смет"


def _positive(value: object) -> Optional[float]:
    """Число больше нуля или None. Ноль и мусор ценой не считаются."""
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def compute_min_price(prices: Optional[dict]) -> Optional[float]:
    """Цена работы для расчёта сметы: сначала «Из смет», потом минимум по прайсам."""
    if not isinstance(prices, dict) or not prices:
        return None

    from_estimates = _positive(prices.get(ESTIMATE_CONTRACTOR))
    if from_estimates is not None:
        return from_estimates

    contractor_prices = []
    for name, value in prices.items():
        if name == ESTIMATE_CONTRACTOR:
            continue
        price = _positive(value)
        if price is not None:
            contractor_prices.append(price)

    return min(contractor_prices) if contractor_prices else None
