"""Приведение цен КП и выбор лучшей цены позиции (план 2026-09-14-zapros-kp.md, фаза 4).

Критерии спецификации 19–21: приведённая цена — без НДС и в единице позиции;
НДС → единица → одно округление; несводимая единица цены не даёт и в минимуме
не участвует; черновая (неподтверждённая) цена в минимуме не участвует; выбор
человека перекрывает минимум, если у выбранного КП есть приведённая
подтверждённая цена. Числа — точные.
"""
from datetime import date
from types import SimpleNamespace

import pytest

from app.services import kp_pricing as kpp


# ---------------------------------------------------------------------------
# НДС
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "price, rate",
    [(1220, 22), (1200, 20), (1100, 10), (1050, 5), (1000, 0)],
)
def test_net_price_exact_for_each_rate(price, rate):
    value, status, reason = kpp.normalized(price, "м2", "м2", "with_vat", rate)
    assert value == 1000.00
    assert reason is None


def test_net_price_without_vat_is_as_is():
    assert kpp.normalized(1220, "м2", "м2", "without_vat", 22)[0] == 1220.00


def test_with_vat_without_rate_uses_default_22():
    assert kpp.DEFAULT_VAT_RATE == 22
    assert kpp.normalized(1220, None, None, "with_vat", None)[0] == 1000.00


# ---------------------------------------------------------------------------
# Единица
# ---------------------------------------------------------------------------

def test_ton_price_in_kg_item():
    value, status, reason = kpp.normalized(45000, "т", "кг", "without_vat", None)
    assert value == 45.00
    assert status == "converted"
    assert reason is None


def test_order_matters_single_rounding():
    # 1 ₽/кг с НДС 22 % в позиции «т»: 1/1,22 × 1000 = 819,672… → 819,67.
    # Округлив до копеек сначала (0,82 × 1000), получили бы 820 — ошибку в 33 копейки.
    assert kpp.normalized(1, "кг", "т", "with_vat", 22)[0] == 819.67


def test_bag_vs_kg_no_price_and_reason():
    value, status, reason = kpp.normalized(350, "мешок", "кг", "without_vat", None)
    assert value is None
    assert status == "incompatible"
    assert "мешок" in reason and "кг" in reason


def test_unit_not_specified_taken_as_is():
    value, status, reason = kpp.normalized(500, None, "м2", "without_vat", None)
    assert value == 500.00
    assert status == "unknown"
    assert reason is None
    assert kpp.normalized(500, "м2", "", "without_vat", None)[0] == 500.00


def test_hundred_m2_price():
    assert kpp.normalized(5000, "100 м2", "м2", "without_vat", None)[0] == 50.00


def test_tiny_price_not_rounded_to_zero():
    assert kpp.normalized(4, "т", "кг", "without_vat", None)[0] == 0.004


# ---------------------------------------------------------------------------
# Лучшая цена позиции
# ---------------------------------------------------------------------------

def _item(unit="кг", selected=None, item_type="material"):
    return SimpleNamespace(id="i1", unit=unit, selected_offer_id=selected, item_type=item_type)


def _offer(oid, supplier, vat_mode="without_vat", vat_rate=None, includes=False):
    return SimpleNamespace(
        id=oid, supplier_name=supplier, offer_date=date(2026, 9, 1),
        vat_mode=vat_mode, vat_rate=vat_rate, includes_materials=includes,
    )


def _price(offer_id, price, unit="кг", confirmed=True, includes=None, source="manual"):
    return SimpleNamespace(
        offer_id=offer_id, item_id="i1", price=price, unit=unit, confirmed=confirmed,
        includes_materials=includes, source=source, confidence=None, name_in_offer=None,
    )


def test_minimum_by_normalized_price():
    offers = [_offer("a", "А", "with_vat", 22), _offer("b", "Б")]
    prices = [_price("a", 1220), _price("b", 1100)]
    best = kpp.best_for_item(_item(), offers, prices)
    # 1220 с НДС = 1000 без НДС, дешевле 1100 без НДС.
    assert best["offer_id"] == "a"
    assert best["price"] == 1000.00
    assert best["selected"] is False
    assert best["supplier_name"] == "А"
    assert best["offer_date"] == date(2026, 9, 1)
    assert best["offers_count"] == 2


def test_minimum_ignores_draft():
    offers = [_offer("a", "А"), _offer("b", "Б")]
    prices = [_price("a", 900, confirmed=False, source="ai"), _price("b", 1000)]
    best = kpp.best_for_item(_item(), offers, prices)
    assert best["offer_id"] == "b"
    assert best["offers_count"] == 1


def test_only_drafts_no_best():
    offers = [_offer("a", "А")]
    assert kpp.best_for_item(_item(), offers, [_price("a", 900, confirmed=False)]) is None


def test_minimum_ignores_incompatible_unit():
    offers = [_offer("a", "А"), _offer("b", "Б")]
    prices = [_price("a", 10, unit="мешок"), _price("b", 1000)]
    best = kpp.best_for_item(_item(), offers, prices)
    assert best["offer_id"] == "b"


def test_selected_without_normalized_price_falls_back_to_minimum():
    offers = [_offer("a", "А"), _offer("b", "Б"), _offer("c", "В")]
    prices = [_price("a", 900), _price("b", 10, unit="мешок"), _price("c", 800, confirmed=False)]
    for selected in ("b", "c", "нет-такого"):
        best = kpp.best_for_item(_item(selected=selected), offers, prices)
        assert best["offer_id"] == "a", selected
        assert best["selected"] is False


def test_includes_materials_of_price_overrides_offer():
    offers = [_offer("a", "А", includes=True), _offer("b", "Б", includes=False)]
    item = _item(unit="м2", item_type="work")
    best = kpp.best_for_item(item, offers, [_price("a", 500, unit="м2", includes=False)])
    assert best["includes_materials"] is False
    best = kpp.best_for_item(item, offers, [_price("b", 500, unit="м2", includes=True)])
    assert best["includes_materials"] is True
    best = kpp.best_for_item(item, offers, [_price("a", 500, unit="м2")])
    assert best["includes_materials"] is True


def test_tie_goes_to_earlier_offer():
    offers = [_offer("a", "А"), _offer("b", "Б")]
    best = kpp.best_for_item(_item(), offers, [_price("b", 1000), _price("a", 1000)])
    assert best["offer_id"] == "a"
