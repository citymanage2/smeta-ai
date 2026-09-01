"""Что считается изменением цены — одно правило на все пути записи в прайс.

`updated_at` у позиции прайса отвечает на один вопрос: **когда эта цена стала
такой**. Менеджер смотрит на неё, чтобы понять, насколько цена свежая, поэтому
дату двигает только переоценка, а не любое касание записи: переименование
позиции, заполнение единицы, повторная запись того же числа и перезаливка того
же файла дату не трогают.

Поэтому у `PriceWork.updated_at` / `PriceMaterial.updated_at` **нет** `onupdate`:
он обновлял бы дату на каждый UPDATE и вернул бы ровно ту проблему, которую
чиним. Дату проставляет вызывающий код — и только когда эта функция сказала «да».

Правило одно на все пути записи (пакетное добавление из редактора, ручная правка
каталога, загрузка прайса файлом, перезаливка объединённого файла): иначе одна и
та же позиция получала бы разную дату в зависимости от того, каким путём её
тронули.
"""
from typing import Optional

from app.utils.unit_normalizer import canonical_unit

# Порог сравнения денег: полкопейки. Цены приезжают из xlsx и из ответов ИИ, где
# 1234.56 легко превращается в 1234.5600000000001 — такая разница переоценкой не
# является. Меньше копейки цена в прайсе не меняется.
MONEY_EPS = 0.005


def _amount(value: object) -> Optional[float]:
    """Число цены или None. Ноль, пустая строка и мусор — это «цены нет»."""
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _normalized_prices(prices: Optional[dict]) -> dict:
    """Словарь «подрядчик → цена» без записей, в которых цены на самом деле нет."""
    if not isinstance(prices, dict):
        return {}
    result = {}
    for name, value in prices.items():
        amount = _amount(value)
        if amount is not None:
            result[str(name)] = amount
    return result


def _amount_changed(old: Optional[float], new: Optional[float]) -> bool:
    """Изменилось ли число цены. Появление и исчезновение цены — изменение."""
    if old is None and new is None:
        return False
    if old is None or new is None:
        return True
    return abs(old - new) > MONEY_EPS


def unit_changed(old_unit: Optional[str], new_unit: Optional[str]) -> bool:
    """Сменилась ли единица измерения — то есть за что назначена цена.

    Единица — часть цены, а не подпись: «500 ₽ за м2» и «500 ₽ за м3» — разные
    цены (правило №8 в CLAUDE.md). Но изменением считается только смена между
    двумя **непустыми** написаниями: пустая единица ничего не утверждает о цене,
    и её появление («» → «м2») — уточнение описания, а не переоценка. Иначе
    первая же загрузка прайса с заполненными единицами сдвинула бы дату у всех
    позиций, у которых единицы не было.
    """
    old = canonical_unit(old_unit).strip().lower()
    new = canonical_unit(new_unit).strip().lower()
    if not old or not new:
        return False
    return old != new


def price_changed(
    old_price: object,
    new_price: object,
    old_unit: Optional[str] = None,
    new_unit: Optional[str] = None,
) -> bool:
    """Изменилась ли цена материала: число или единица, за которую она назначена."""
    if _amount_changed(_amount(old_price), _amount(new_price)):
        return True
    return unit_changed(old_unit, new_unit)


def prices_changed(
    old_prices: Optional[dict],
    new_prices: Optional[dict],
    old_unit: Optional[str] = None,
    new_unit: Optional[str] = None,
) -> bool:
    """Изменился ли набор цен работы.

    У работы цена не одна: по цене на подрядчика плюс цена «Из смет». Переоценка —
    это появление, исчезновение или изменение любой из них: расчёт сметы берёт из
    набора одно число (`price_min.compute_min_price`), и сегодняшний минимум
    завтра может смениться на другую цену того же набора.
    """
    old = _normalized_prices(old_prices)
    new = _normalized_prices(new_prices)

    if set(old) != set(new):
        return True
    for name, old_amount in old.items():
        if _amount_changed(old_amount, new.get(name)):
            return True

    return unit_changed(old_unit, new_unit)
