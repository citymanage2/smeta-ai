"""Какая цена работы попадает в расчёт сметы.

У работы в прайсе несколько цен: по одной на подрядчика плюс цена, добавленная
из сметы (псевдо-подрядчик «Из смет»), и цены из КП (подрядчики «КП: <поставщик>»).
В расчёт идёт `min_price` — одно число, и правило его выбора должно быть
одинаковым везде, где прайс пишется: при пакетном добавлении из редактора, при
ручной правке каталога, при загрузке прайса файлом, эталоном и запросом КП.
Иначе одна и та же работа получала бы разную цену в зависимости от того, каким
путём её последний раз тронули.

**Решение пользователя (2026-08-03): приоритет у цены из смет.** Если она есть —
берём её. Цены подрядчиков работают, только когда цены из смет нет.

**Решение пользователя (2026-09-14) поверх него: выше всех — цены из КП.**
Цена, которую отдел производства получил от поставщика под конкретный запрос и
подтвердил, свежее и точнее цены из прошлой сметы. Поэтому порядок такой:
минимум по ключам «КП: …» → «Из смет» → минимум по остальным подрядчикам
(план `plans/2026-09-14-zapros-kp.md`, фаза 7).

Раз имя «КП: …» даёт приоритет, записывает его только запрос КП
(`services/kp_pricelist.py`). Загрузка прайса файлом и ручная правка каталога
такое имя подрядчика не принимают (`is_reserved_contractor`): иначе подрядчик,
названный в файле «КП: Х», молча перебил бы «Из смет».
"""
from typing import Optional

# Псевдо-подрядчик: под этим именем в прайс попадают цены из смет. Отдельное имя
# нужно, чтобы такие цены не смешивались с настоящими прайсами подрядчиков и их
# было видно в каталоге.
ESTIMATE_CONTRACTOR = "Из смет"

# Префикс подрядчика цены из КП: «КП: ООО Стройка».
KP_CONTRACTOR_PREFIX = "КП: "


def kp_contractor(supplier_name: str) -> str:
    """Ключ цены из КП в `PriceWork.prices`."""
    return KP_CONTRACTOR_PREFIX + (supplier_name or "").strip()


def is_kp_contractor(name: object) -> bool:
    """Ключ цены из КП — ровно тот, что пишет `kp_contractor`."""
    return str(name).startswith(KP_CONTRACTOR_PREFIX)


def is_reserved_contractor(name: object) -> bool:
    """Имя подрядчика, которое не принимают пути записи прайса, кроме запроса КП.

    Шире, чем `is_kp_contractor`: «кп:Х» и « КП: Х» тоже отклоняются, чтобы
    человек не завёл похожее имя, которое на экране не отличить от настоящего.
    """
    return str(name or "").strip().lower().startswith(KP_CONTRACTOR_PREFIX.strip().lower())


def _positive(value: object) -> Optional[float]:
    """Число больше нуля или None. Ноль и мусор ценой не считаются."""
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def compute_min_price(prices: Optional[dict]) -> Optional[float]:
    """Цена работы для расчёта сметы: минимум «КП: …», потом «Из смет», потом минимум по прайсам."""
    if not isinstance(prices, dict) or not prices:
        return None

    kp_prices = []
    contractor_prices = []
    for name, value in prices.items():
        if name == ESTIMATE_CONTRACTOR:
            continue
        price = _positive(value)
        if price is None:
            continue
        if is_kp_contractor(name):
            kp_prices.append(price)
        else:
            contractor_prices.append(price)

    if kp_prices:
        return min(kp_prices)

    from_estimates = _positive(prices.get(ESTIMATE_CONTRACTOR))
    if from_estimates is not None:
        return from_estimates

    return min(contractor_prices) if contractor_prices else None


def reserved_contractors(prices: Optional[dict]) -> list[str]:
    """Имена подрядчиков с зарезервированным префиксом — для отказа с причиной."""
    if not isinstance(prices, dict):
        return []
    return [str(name) for name in prices if is_reserved_contractor(name)]


def reserved_contractor_error(names: list[str]) -> str:
    listed = ", ".join(f"«{n}»" for n in sorted(set(names))[:10])
    return (
        f"Имя подрядчика {listed} зарезервировано: цены «КП: …» записывает только "
        "запрос КП. Переименуйте подрядчика."
    )
