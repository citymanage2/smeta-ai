import pytest
from app.utils.unit_normalizer import normalize_unit_quantity, normalize_items


class TestNormalizeUnitQuantity:
    def test_100_m2_with_space(self):
        unit, qty, changed = normalize_unit_quantity("100 м2", 0.1)
        assert unit == "м2"
        assert abs(qty - 10.0) < 1e-9
        assert changed is True

    def test_1000_sht(self):
        unit, qty, changed = normalize_unit_quantity("1000 шт", 0.005)
        assert unit == "шт"
        assert abs(qty - 5.0) < 1e-9
        assert changed is True

    def test_0001_t(self):
        unit, qty, changed = normalize_unit_quantity("0.001 т", 5000)
        assert unit == "т"
        assert abs(qty - 5.0) < 1e-9
        assert changed is True

    def test_trivial_prefix_1(self):
        unit, qty, changed = normalize_unit_quantity("1 пог.м", 3.5)
        assert unit == "пог.м"
        assert qty == 3.5
        assert changed is True

    def test_100_chel_chas(self):
        unit, qty, changed = normalize_unit_quantity("100 чел.-час", 0.5)
        assert unit == "чел.-час"
        assert abs(qty - 50.0) < 1e-9
        assert changed is True

    def test_100_mash_ch(self):
        unit, qty, changed = normalize_unit_quantity("100 маш.-ч", 2.0)
        assert unit == "маш.-ч"
        assert abs(qty - 200.0) < 1e-9
        assert changed is True

    def test_1000_tkm(self):
        unit, qty, changed = normalize_unit_quantity("1000 т·км", 0.1)
        assert unit == "т·км"
        assert abs(qty - 100.0) < 1e-9
        assert changed is True

    def test_no_space_100m2(self):
        unit, qty, changed = normalize_unit_quantity("100м2", 0.1)
        assert unit == "м2"
        assert abs(qty - 10.0) < 1e-9
        assert changed is True

    def test_unknown_unit_ml(self):
        unit, qty, changed = normalize_unit_quantity("500 мл", 1.0)
        assert unit == "500 мл"
        assert changed is False

    def test_unknown_unit_etazh(self):
        unit, qty, changed = normalize_unit_quantity("2 этаж", 1.0)
        assert unit == "2 этаж"
        assert changed is False

    def test_no_prefix_m2(self):
        unit, qty, changed = normalize_unit_quantity("м2", 5.0)
        assert unit == "м2"
        assert qty == 5.0
        assert changed is False

    def test_empty_string(self):
        unit, qty, changed = normalize_unit_quantity("", 1.0)
        assert changed is False

    def test_none_unit(self):
        unit, qty, changed = normalize_unit_quantity(None, 1.0)
        assert changed is False

    def test_empty_base_unit(self):
        unit, qty, changed = normalize_unit_quantity("100 ", 1.0)
        assert changed is False

    def test_quantity_none(self):
        unit, qty, changed = normalize_unit_quantity("100 м2", None)
        assert unit == "м2"
        assert qty is None
        assert changed is True

    def test_zero_prefix_not_changed(self):
        unit, qty, changed = normalize_unit_quantity("0 м2", 5.0)
        assert unit == "0 м2"
        assert qty == 5.0
        assert changed is False

    def test_quantity_string_not_changed(self):
        unit, qty, changed = normalize_unit_quantity("100 м2", "не_число")
        assert unit == "100 м2"
        assert changed is False

    def test_quantity_numeric_string_works(self):
        unit, qty, changed = normalize_unit_quantity("100 м2", "0.1")
        assert unit == "м2"
        assert abs(qty - 10.0) < 1e-6
        assert changed is True


class TestNormalizeItems:
    def test_notes_appended(self):
        items = [{"unit": "100 м2", "quantity": 0.1, "notes": "важно"}]
        result = normalize_items(items)
        assert result[0]["unit"] == "м2"
        assert "важно" in result[0]["notes"]
        assert "нормализована" in result[0]["notes"]

    def test_notes_created_when_empty(self):
        items = [{"unit": "100 м2", "quantity": 0.1, "notes": ""}]
        result = normalize_items(items)
        assert "нормализована" in result[0]["notes"]
        assert not result[0]["notes"].startswith(";")

    def test_no_change_for_normal_unit(self):
        items = [{"unit": "м2", "quantity": 5.0}]
        result = normalize_items(items)
        assert result[0]["unit"] == "м2"
        assert result[0]["quantity"] == 5.0
        assert "notes" not in result[0]

    def test_original_not_mutated(self):
        original = [{"unit": "100 м2", "quantity": 0.1}]
        normalize_items(original)
        assert original[0]["unit"] == "100 м2"

    def test_idempotent(self):
        items = [{"unit": "м2", "quantity": 10.0}]
        once = normalize_items(items)
        twice = normalize_items(once)
        assert once == twice
