"""
Цены от ИИ: приведение типа и отбрасывание невозможных значений.

Два доказанных дефекта (ревью 2026-07-30):

1. `work_price="1500"` (строка вместо числа) при `qty=3` роняло сборку сметы:
   `TypeError: type str doesn't define __round__`. Хуже обычного падения — к
   этому моменту все запросы к ИИ уже оплачены, а чекпоинт `_stage="pre_excel"`
   сохранён, поэтому возобновление шло сразу в сборку с теми же данными и падало
   снова. Задача становилась неизлечимой без правки БД.

2. `work_price=-1500` не падало вовсе и давало смету с `grand_total=-4635.0`,
   которая ушла бы на тендер.

Правило: цена, которой не может быть (не число, отрицательная, NaN/inf),
трактуется как «цены нет» — позиция помечается «Цена не определена», а не роняет
задачу и не искажает итог.

План: plans/2026-07-30-ispravlenie-nahodok-code-review.md, Фаза 1.
"""
import sys
from unittest.mock import MagicMock

import pytest

sys.modules.setdefault("fitz", MagicMock())

from app.utils.price_coercion import coerce_price, coerce_qty  # noqa: E402


# ---------------------------------------------------------------------------
# coerce_price
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    (1500, 1500.0),
    (1500.5, 1500.5),
    ("1500", 1500.0),          # ИИ ответил числом в кавычках
    ("1500.50", 1500.5),
    ("1500,50", 1500.5),       # десятичная запятая — обычное дело в русских ответах
    (" 1500 ", 1500.0),
    ("1 500", 1500.0),         # разряды пробелом
    ("1 500,50", 1500.5),      # неразрывный пробел
    ("1500 руб.", 1500.0),     # хвост с единицами
])
def test_coerce_price_accepts_real_prices(raw, expected):
    assert coerce_price(raw) == pytest.approx(expected)


@pytest.mark.parametrize("raw", [
    None,
    "",
    "   ",
    "нет данных",
    "не определена",
    -1500,
    "-1500",
    0,
    "0",
    float("nan"),
    float("inf"),
    float("-inf"),
    [],
    {},
    True,                      # bool — не цена, хотя формально int
])
def test_coerce_price_rejects_impossible_values(raw):
    assert coerce_price(raw) is None


def test_coerce_price_rejects_absurdly_large():
    """Защита от галлюцинации вида 10^15: такой цены в смете быть не может,
    а в итог она внесёт мусор, который никто не заметит глазами."""
    assert coerce_price(10**15) is None
    assert coerce_price(999_999_999.0) == pytest.approx(999_999_999.0)


# ---------------------------------------------------------------------------
# coerce_qty
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    (3, 3.0),
    (0.333, 0.333),
    ("3", 3.0),
    ("0,333", 0.333),
    (None, 0.0),
    ("", 0.0),
    ("мусор", 0.0),
    (-5, 0.0),                 # отрицательный объём работ невозможен
    (float("nan"), 0.0),
])
def test_coerce_qty(raw, expected):
    assert coerce_qty(raw) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Генератор сметы больше не падает и не искажает итог
# ---------------------------------------------------------------------------

def _item(**over):
    base = {"type": "Работа", "name": "Кладка", "unit": "м2",
            "quantity": 3, "work_price": 1500, "material_price": None}
    base.update(over)
    return base


def test_estimate_xlsx_survives_string_price():
    """Ровно тот случай, что делал задачу неизлечимой."""
    from app.utils.xlsx_exporter import generate_estimate_xlsx

    data, total = generate_estimate_xlsx([_item(work_price="1500")])
    assert data  # файл сформирован
    # Строка "1500" — валидное число, его надо посчитать, а не выбросить.
    assert total == pytest.approx(4635.0)


def test_estimate_xlsx_drops_negative_price():
    """Отрицательная цена не должна давать отрицательную смету."""
    from app.utils.xlsx_exporter import generate_estimate_xlsx

    data, total = generate_estimate_xlsx([_item(work_price=-1500)])
    assert data
    assert total == 0.0


def test_estimate_xlsx_survives_garbage_price():
    """Нечисловой мусор → позиция без цены, задача доходит до конца."""
    from app.utils.xlsx_exporter import generate_estimate_xlsx

    data, total = generate_estimate_xlsx([_item(work_price="цена по запросу")])
    assert data
    assert total == 0.0


def test_estimate_xlsx_normal_case_unchanged():
    """Контроль: обычная смета считается ровно как раньше."""
    from app.utils.xlsx_exporter import generate_estimate_xlsx

    _, total = generate_estimate_xlsx([_item()])
    # 3 * 1500 = 4500 работ, +3% накладных = 4635
    assert total == pytest.approx(4635.0)


def test_estimate_xlsx_mixed_valid_and_broken():
    """Испорченная позиция не должна утаскивать за собой валидные."""
    from app.utils.xlsx_exporter import generate_estimate_xlsx

    _, total = generate_estimate_xlsx([
        _item(),
        _item(work_price="мусор"),
        _item(work_price=-100),
    ])
    assert total == pytest.approx(4635.0)
