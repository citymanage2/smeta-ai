"""Приведение цен и объёмов из ответов ИИ к числам.

Ответ ИИ — это текст, который мы просим быть JSON'ом с числами, но гарантии нет.
Пришедшая строка `"1500"` роняла сборку сметы (`TypeError` в `round`), причём
неизлечимо: к моменту сборки все запросы уже оплачены, а чекпоинт `pre_excel`
сохранён, поэтому перезапуск шёл в ту же точку и падал снова. Отрицательная цена
не падала вовсе — давала смету с отрицательным итогом.

Правило: значение, которого у цены быть не может, трактуется как «цены нет».
Позиция помечается «Цена не определена» — это видно человеку и поправимо руками,
в отличие от упавшей задачи и молча искажённого итога.
"""
from __future__ import annotations

import math
import re
from typing import Any, Optional

# Разряды могут прийти обычным, неразрывным или узким неразрывным пробелом.
_SPACES = (" ", " ", " ", " ")

# Первое число в строке: "1500 руб." / "1 500,50" / "-1500".
_NUMBER_RE = re.compile(r"-?\d+(?:[.,]\d+)?")

# Верхняя граница разумной цены за единицу, в рублях. Выше — галлюцинация ИИ
# (видели порядки 10^15), которая в итоге сметы визуально не отличима от нормы.
# Миллиард за единицу заведомо больше любой реальной позиции в наших сметах.
MAX_REASONABLE_PRICE = 1_000_000_000.0


def _to_float(value: Any) -> Optional[float]:
    """Вытащить число из числа или строки. None, если не получилось."""
    # bool — подкласс int, но `True` как цена это всегда ошибка данных.
    if isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        num = float(value)
    elif isinstance(value, str):
        s = value
        for sp in _SPACES:
            s = s.replace(sp, "")
        m = _NUMBER_RE.search(s)
        if not m:
            return None
        try:
            num = float(m.group(0).replace(",", "."))
        except ValueError:
            return None
    else:
        return None

    # NaN/inf проходят float() молча и портят все последующие суммы.
    if not math.isfinite(num):
        return None
    return num


def coerce_price(value: Any) -> Optional[float]:
    """Цена за единицу → положительный float, либо None если цены нет.

    None означает именно «цены нет»: ноль, отрицательное, нечисловое и абсурдно
    большое равнозначны отсутствию — все они не должны попадать в смету.
    """
    num = _to_float(value)
    if num is None:
        return None
    if num <= 0:
        return None
    if num > MAX_REASONABLE_PRICE:
        return None
    return num


def coerce_qty(value: Any) -> float:
    """Объём → неотрицательный float. Отсутствие и мусор → 0.0.

    В отличие от цены здесь возвращается 0.0, а не None: объём участвует в
    умножении, и ноль даёт корректную нулевую стоимость без ветвлений у каждого
    вызывающего.
    """
    num = _to_float(value)
    if num is None or num < 0:
        return 0.0
    return num
