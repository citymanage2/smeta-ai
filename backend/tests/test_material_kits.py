"""Комплект материалов к каркасной работе: распознавание, объёмы, дедупликация.

Числа в тестах точные и проверяются вручную: ошибка в норме расхода уезжает в
каждую смету. Опорный пример — строка 155 реальной сметы:
«Устройство перегородок из ГВЛ с одинарным металлическим каркасом и двухслойной
обшивкой с обеих сторон», м², 5,475 → листов ГВЛ 5,475 × 2 слоя × 2 стороны = 21,9 м².
"""
import sys
from unittest.mock import MagicMock

sys.modules.setdefault('fitz', MagicMock())

from app.services.material_kits import (  # noqa: E402
    KIT_ADDED_PREFIX,
    KIT_MISMATCH_PREFIX,
    expand_completeness_items,
    match_kit,
)

PARTITION_2X2 = (
    "Устройство перегородок из гипсоволокнистых листов (ГВЛ) с одинарным "
    "металлическим каркасом и двухслойной обшивкой с обеих сторон: "
    "с одним дверным проемом"
)


def _work(name: str, unit: str = "м2", qty: float = 5.475, **extra) -> dict:
    return {"type": "Работа", "name": name, "unit": unit, "quantity": qty, **extra}


def _material(name: str, unit: str = "м2", qty=None, **extra) -> dict:
    return {"type": "Материал", "name": name, "unit": unit, "quantity": qty, **extra}


def _added(items: list[dict]) -> dict[str, dict]:
    """Добавленные комплектом позиции по имени."""
    return {
        it["name"]: it
        for it in items
        if str(it.get("notes") or "").startswith(KIT_ADDED_PREFIX)
    }


def _find(items: list[dict], fragment: str) -> dict:
    """Материал по фрагменту имени.

    Ищем только среди материалов: в наименовании работы тоже встречается и «ГВЛ»,
    и «листов», и поиск по всем строкам находил бы саму работу.
    """
    lowered = fragment.lower()
    for item in items:
        if item.get("type") != "Материал":
            continue
        if lowered in str(item.get("name", "")).lower():
            return item
    raise AssertionError(f"материал {fragment!r} не найден среди {[i['name'] for i in items]}")


# ── распознавание системы ────────────────────────────────────────────────────

def test_partition_recognised_with_layers_and_sides():
    kit = match_kit(PARTITION_2X2, "м2")
    assert kit is not None
    assert kit.params.layers == 2
    assert kit.params.sides == 2
    assert kit.params.explicit is True


def test_partition_defaults_when_name_says_nothing():
    """«Устройство перегородок из ГКЛ» — конструкция не описана: 1 слой × 2 стороны."""
    kit = match_kit("Устройство перегородок из ГКЛ", "м2")
    assert kit is not None
    assert (kit.params.layers, kit.params.sides) == (1, 2)
    assert kit.params.explicit is False


def test_lining_is_one_sided():
    kit = match_kit("Облицовка стен гипсокартонными листами по металлическому каркасу", "м2")
    assert kit is not None
    assert kit.params.sides == 1


def test_demolition_is_not_expanded():
    """Разборка перегородки материалов не требует — комплект к ней приезжать не должен."""
    for name in (
        "Разборка перегородок из ГКЛ",
        "Демонтаж перегородок из гипсокартона",
        "Снятие обшивки из ГВЛ",
    ):
        assert match_kit(name, "м2") is None, name


def test_wrong_unit_is_not_expanded():
    """Норма задана на 1 м². Расценка в м³ или пог. м умножилась бы не на ту величину."""
    assert match_kit(PARTITION_2X2, "м3") is None
    assert match_kit(PARTITION_2X2, "м") is None


def test_unrelated_work_is_not_recognised():
    assert match_kit("Уплотнение грунта щебнем", "м2") is None


# ── объёмы комплекта ─────────────────────────────────────────────────────────

def test_sheets_quantity_is_layers_times_sides():
    result = expand_completeness_items([_work(PARTITION_2X2)])
    sheets = _find(result.items, "ГВЛ")
    assert sheets["quantity"] == 21.9
    assert sheets["unit"] == "м2"
    assert sheets["type"] == "Материал"


def test_full_partition_kit_quantities():
    """Весь комплект на 5,475 м² перегородки С-112. Числа сверены с таблицей плана."""
    result = expand_completeness_items([_work(PARTITION_2X2)])
    added = _added(result.items)

    expected = {
        "профиль стоечный": 10.95,   # 2,0 пог.м/м²
        "профиль направляющий": 4.38,  # 0,8 пог.м/м²
        "лента уплотнительная": 4.38,  # 0,8 пог.м/м²
        "шурупы": None,               # проверяются отдельно: их две позиции
        "дюбель": 9,                  # 1,6 шт/м² = 8,76 → 9 (штуки не дробят)
        "лента армирующая": 6.57,     # 1,2 пог.м/м²
        "шпакл": 2.738,               # 0,5 кг/м²
        "грунтовка": 0.548,           # 0,1 л/м²
        "плита минераловатная": 5.475,  # 1,0 м²/м²
    }
    for fragment, qty in expected.items():
        if qty is None:
            continue
        item = _find(list(added.values()), fragment)
        assert item["quantity"] == qty, f"{fragment}: {item['quantity']} != {qty}"


def test_screws_second_layer_only_when_two_layers():
    two = _added(expand_completeness_items([_work(PARTITION_2X2)]).items)
    assert _find(list(two.values()), "TN 25")["quantity"] == 110   # 20 шт/м² → 109,5 → 110
    assert _find(list(two.values()), "TN 35")["quantity"] == 187   # 34 шт/м² → 186,15 → 187

    one = _added(expand_completeness_items(
        [_work("Устройство перегородок из ГКЛ с однослойной обшивкой с обеих сторон")]
    ).items)
    assert "TN 25" in " ".join(one)
    assert "TN 35" not in " ".join(one), "второй слой не обшивается — шурупов TN 35 быть не должно"


def test_added_note_shows_the_formula():
    result = expand_completeness_items([_work(PARTITION_2X2)])
    note = _find(result.items, "ГВЛ")["notes"]
    assert note.startswith(KIT_ADDED_PREFIX)
    assert "21,9" in note and "5,475" in note
    assert "2 слоя" in note and "2 стороны" in note


def test_default_params_are_stated_in_the_note():
    """Приняли конструкцию за человека — человек должен это увидеть в строке."""
    result = expand_completeness_items([_work("Устройство перегородок из ГКЛ")])
    note = _find(result.items, "ГКЛ")["notes"]
    assert "по умолчанию" in note.lower()


def test_gvl_work_gets_gvl_sheets_and_gkl_work_gets_gkl():
    gvl = expand_completeness_items([_work(PARTITION_2X2)]).items
    assert "ГВЛ" in _find(gvl, "лист")["name"]

    gkl = expand_completeness_items([_work("Устройство перегородок из ГКЛ")]).items
    assert "ГКЛ" in _find(gkl, "лист")["name"]


# ── дедупликация и расхождения ───────────────────────────────────────────────

def test_existing_material_is_not_duplicated():
    items = [
        _work(PARTITION_2X2),
        _material("Листы гипсоволокнистые ГВЛ 12,5 мм", qty=21.9),
    ]
    result = expand_completeness_items(items)
    sheets = [it for it in result.items if "гвл" in it["name"].lower() and it["type"] == "Материал"]
    assert len(sheets) == 1, "лист ГВЛ уже был в перечне — второй раз добавлять нельзя"


def test_existing_material_with_other_quantity_is_flagged_not_changed():
    items = [
        _work(PARTITION_2X2),
        _material("Листы гипсоволокнистые ГВЛ 12,5 мм", qty=5.475),
    ]
    result = expand_completeness_items(items)
    sheets = _find(result.items, "гипсоволокнистые")
    assert sheets["quantity"] == 5.475, "объём заказчика правим только с его ведома"
    assert sheets["notes"].startswith(KIT_MISMATCH_PREFIX)
    assert "21,9" in sheets["notes"]
    assert result.flagged == 1


def test_close_quantity_is_not_flagged():
    """Расхождение в пределах 5 % — подрезка и округление, а не ошибка."""
    items = [
        _work(PARTITION_2X2),
        _material("Листы гипсоволокнистые ГВЛ 12,5 мм", qty=22.4),
    ]
    result = expand_completeness_items(items)
    assert result.flagged == 0
    assert not str(_find(result.items, "гипсоволокнистые").get("notes") or "").startswith(
        KIT_MISMATCH_PREFIX
    )


def test_existing_material_without_quantity_is_filled():
    """Пустой объём терять нечего — проставляем расчётный и говорим об этом."""
    items = [
        _work(PARTITION_2X2),
        _material("Профиль стоечный ПС 50х50", unit="м", qty=None),
    ]
    result = expand_completeness_items(items)
    profile = _find(result.items, "Профиль стоечный")
    assert profile["quantity"] == 10.95
    assert profile["notes"].startswith(KIT_ADDED_PREFIX)


def test_insulation_of_customer_is_recognised_by_keywords():
    """«Материалы теплоизоляционные из минеральных волокон» — тот же утеплитель."""
    items = [
        _work(PARTITION_2X2),
        _material("Материалы теплоизоляционные из минеральных волокон", qty=5.639),
    ]
    result = expand_completeness_items(items)
    insulation = [
        it for it in result.items
        if it["type"] == "Материал" and ("минерал" in it["name"].lower() or "теплоизол" in it["name"].lower())
    ]
    assert len(insulation) == 1, "утеплитель уже есть — свой добавлять нельзя"


# ── порядок, листы, посторонние строки ───────────────────────────────────────

def test_kit_is_inserted_after_own_materials_before_next_work():
    items = [
        _work(PARTITION_2X2),
        _material("Плиты минераловатные ТЕХНОРУФ 45", unit="м3", qty=0.51),
        _work("Уплотнение грунта щебнем", qty=766.6),
    ]
    result = expand_completeness_items(items)
    names = [it["name"] for it in result.items]
    assert names[0] == PARTITION_2X2
    assert names[1] == "Плиты минераловатные ТЕХНОРУФ 45"
    assert names[-1] == "Уплотнение грунта щебнем"
    assert len(names) > 3


def test_new_items_inherit_sheet_of_the_work():
    result = expand_completeness_items([_work(PARTITION_2X2, sheet="Раздел 2")])
    for item in result.items:
        assert item.get("sheet") == "Раздел 2"


def test_untouched_items_are_returned_as_is():
    original = [
        _work("Уплотнение грунта щебнем", qty=766.6),
        _material("Щебень из природного камня фракции 40-70 мм", unit="м3", qty=39.096),
    ]
    result = expand_completeness_items([dict(it) for it in original])
    assert result.items == original
    assert result.added == 0


def test_handled_works_are_reported_for_the_ai_prompt():
    result = expand_completeness_items([_work(PARTITION_2X2), _work("Уплотнение грунта щебнем")])
    assert PARTITION_2X2 in result.handled_works
    assert "Уплотнение грунта щебнем" not in result.handled_works


def test_work_without_quantity_is_skipped():
    """Без объёма работы считать нечего — молча добавлять нули нельзя."""
    result = expand_completeness_items([_work(PARTITION_2X2, qty=None)])
    assert result.added == 0
    assert len(result.items) == 1
