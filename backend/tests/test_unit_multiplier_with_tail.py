"""Кратность единицы с уточнением: «1000 м3 грунта» — это тысяча кубов.

В гранд-смете единица расценки почти всегда идёт с хвостом: «1000 м3 грунта»,
«100 м3 материала основания», «1000 м2 поверхности», «1 т груза». Нормализатор
знал только чистые единицы («100 м2»), поэтому такие строки проезжали мимо: в
смете оставался объём 2,164 вместо 2164, а цена за «м3» из прайса к позиции не
подходила вовсе — единицы считались разными по природе.

Числа в тестах точные: ошибка здесь — это ошибка в тысячу раз на тендере.
"""
import pytest

from app.utils.unit_compat import (
    STATUS_CONVERTED,
    STATUS_INCOMPATIBLE,
    STATUS_SAME,
    compare_units,
    convert_price,
)
from app.utils.unit_normalizer import (
    base_unit,
    normalize_items,
    normalize_unit_quantity,
    unit_price_factor,
)


class TestBaseUnit:
    @pytest.mark.parametrize(
        "written,expected",
        [
            ("м3 грунта", "м3"),
            ("м3 материала основания", "м3"),
            ("м2 поверхности", "м2"),
            ("т груза", "т"),
            ("т конструкций", "т"),
            ("м трубопровода", "м"),
            ("шт. изделий", "шт"),
            ("м3 материала основания (в плотном теле)", "м3"),
            # Уточнение не обязано быть — чистая единица тоже единица.
            ("м2", "м2"),
            ("кв.м", "м2"),
            ("т·км", "т·км"),
        ],
    )
    def test_tail_dropped(self, written, expected):
        assert base_unit(written) == expected

    @pytest.mark.parametrize(
        "written",
        [
            "слоя",            # не единица вовсе
            "бухта провода",   # голова не единица — угадывать нечего
            "м2 в 2 слоя",     # цифра в хвосте: вдруг она часть единицы
            "мешок цемента",
            "",
            None,
        ],
    )
    def test_unknown_left_alone(self, written):
        assert base_unit(written) is None


class TestQuantityConverted:
    @pytest.mark.parametrize(
        "unit,qty,new_unit,new_qty",
        [
            ("1000 м3 грунта", 2.164, "м3", 2164.0),
            ("1000 м3 грунта", 17.2338, "м3", 17233.8),
            ("100 м3 материала основания", 172.338, "м3", 17233.8),
            ("1000 м2 поверхности", 13.705, "м2", 13705.0),
            ("1 т груза", 2596.8, "т", 2596.8),
            ("1 т груза", 33605.91, "т", 33605.91),
            ("100 м трубопровода", 0.5, "м", 50.0),
            ("10 шт. изделий", 3.0, "шт", 30.0),
            # Чистая единица работала и раньше — проверяем, что не сломали.
            ("100 м2", 0.1, "м2", 10.0),
        ],
    )
    def test_multiplier_applied(self, unit, qty, new_unit, new_qty):
        got_unit, got_qty, changed = normalize_unit_quantity(unit, qty)
        assert changed is True
        assert got_unit == new_unit
        assert got_qty == new_qty

    @pytest.mark.parametrize(
        "unit,qty",
        [
            ("2 слоя", 1.0),
            ("100 м2 в 2 слоя", 1.0),
            ("3 захватки", 2.0),
            ("500 мл", 1.0),
            ("0 м3 грунта", 5.0),
        ],
    )
    def test_left_alone(self, unit, qty):
        got_unit, got_qty, changed = normalize_unit_quantity(unit, qty)
        assert changed is False
        assert got_unit == unit
        assert got_qty == qty

    def test_notes_name_the_conversion(self):
        items = [{"unit": "1000 м3 грунта", "quantity": 2.164}]
        result = normalize_items(items)
        assert result[0]["unit"] == "м3"
        assert result[0]["quantity"] == 2164.0
        assert "1000 м3 грунта → м3" in result[0]["notes"]

    def test_idempotent(self):
        once = normalize_items([{"unit": "1000 м3 грунта", "quantity": 2.164}])
        twice = normalize_items(once)
        assert twice == once

    def test_non_dict_passed_through(self):
        assert normalize_items(["мусор"]) == ["мусор"]


class TestPriceMatching:
    """Цена за «м3» обязана подходить позиции в «1000 м3 грунта»."""

    def test_factor_extracted(self):
        assert unit_price_factor("1000 м3 грунта") == ("м3", 1000.0)
        assert unit_price_factor("1 т груза") == ("т", 1.0)
        assert unit_price_factor("м3 грунта") == ("м3", 1.0)
        assert unit_price_factor("2 слоя") == ("2 слоя", 1.0)

    def test_price_scaled_to_multiplied_unit(self):
        status, factor = compare_units("м3", "1000 м3 грунта")
        assert status == STATUS_CONVERTED
        assert factor == 1000.0
        price, status = convert_price(473, "м3", "1000 м3 грунта")
        assert status == STATUS_CONVERTED
        assert price == 473000.0

    def test_cost_matches_either_way(self):
        """Одна и та же стоимость: 2,164 × 473000 = 2164 × 473 = 1 023 572 ₽."""
        per_thousand, _ = convert_price(473, "м3", "1000 м3 грунта")
        assert per_thousand * 2.164 == pytest.approx(1_023_572.0)
        assert 2164.0 * 473 == 1_023_572.0

    def test_same_unit_under_tail(self):
        status, factor = compare_units("м3", "м3 грунта")
        assert status == STATUS_SAME
        assert factor == 1.0

    def test_incompatible_still_refused(self):
        """Хвост не повод угадывать: сколько килограммов в мешке — не к нам."""
        status, factor = compare_units("кг", "мешок цемента")
        assert status == STATUS_INCOMPATIBLE
        assert factor is None


class TestEstimateReadsForeignItems:
    """Смета чинит перечни, уже лежащие в базе с неразобранной кратностью."""

    def test_source_items_normalized_and_contracted(self):
        import sys
        from unittest.mock import MagicMock

        sys.modules.setdefault("fitz", MagicMock())
        from app.services.task_processor import TaskProcessor

        source = [
            {"type": "Работа", "name": "Разработка грунта", "unit": "1000 м3 грунта", "quantity": 2.164},
            {"type": "Работа", "name": "Перевозка грузов"},  # ИИ не вернул unit
        ]
        items = TaskProcessor._prepare_source_items(source)

        assert items[0]["unit"] == "м3"
        assert items[0]["quantity"] == 2164.0
        assert items[1]["unit"] == ""
        assert items[1]["quantity"] is None
        # Чужая задача не тронута: пометка о пересчёте легла бы в её строки.
        assert source[0]["unit"] == "1000 м3 грунта"
        assert source[0]["quantity"] == 2.164
