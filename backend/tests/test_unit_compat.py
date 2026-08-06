"""Единица измерения — часть ключа цены.

06.08.2026: в смете стояло 73 770 ₽ за килограмм затирки (цена за тонну) и
18 000 ₽ за м2 окраски (цена за 100 м2). Название совпало, единица разошлась в
1000 и в 100 раз, и никто этого не проверил.

Каждый коэффициент здесь закреплён точным числом — как нормы расхода
материалов. Ошибка в коэффициенте молча испортит все будущие сметы.
"""
from app.utils.unit_compat import (
    PRICE_CONVERTED_PREFIX,
    PRICE_UNIT_MISMATCH_PREFIX,
    STATUS_CONVERTED,
    STATUS_INCOMPATIBLE,
    STATUS_SAME,
    STATUS_UNKNOWN,
    append_note,
    compare_units,
    converted_note,
    convert_price,
    mismatch_note,
)


# ---------------------------------------------------------------------------
# Случаи из отчёта пользователя
# ---------------------------------------------------------------------------

def test_tonna_v_kilogrammy_iz_otcheta():
    """Затирка: 73 770 ₽/т в позиции с «кг» → 73,77 ₽/кг."""
    price, status = convert_price(73770, "т", "кг")
    assert status == STATUS_CONVERTED
    assert price == 73.77


def test_sto_kvadratov_v_kvadrat_iz_otcheta():
    """Окраска: 18 000 ₽ за «100 м2» в позиции с «м2» → 180 ₽/м2."""
    price, status = convert_price(18000, "100 м2", "м2")
    assert status == STATUS_CONVERTED
    assert price == 180.0


# ---------------------------------------------------------------------------
# Сводимые единицы: коэффициент точный, а не оценка
# ---------------------------------------------------------------------------

def test_kilogramm_v_tonny():
    """Обратное направление: 50 ₽/кг в позиции с «т» → 50 000 ₽/т."""
    assert convert_price(50, "кг", "т") == (50000.0, STATUS_CONVERTED)


def test_gramm_i_kilogramm():
    assert convert_price(2, "г", "кг") == (2000.0, STATUS_CONVERTED)


def test_litr_v_kubometry():
    """1 м3 = 1000 л: 120 ₽/л → 120 000 ₽/м3."""
    assert convert_price(120, "л", "м3") == (120000.0, STATUS_CONVERTED)


def test_gektar_i_kvadratnye_metry():
    """1 га = 10 000 м2: 500 000 ₽/га → 50 ₽/м2."""
    assert convert_price(500000, "га", "м2") == (50.0, STATUS_CONVERTED)


def test_pogonnyj_metr_i_metr_odno_i_to_zhe():
    """«пог.м» и «м» в смете — одна и та же длина, пересчёта не нужно."""
    assert convert_price(340, "пог.м", "м") == (340.0, STATUS_SAME)
    assert convert_price(340, "м.п.", "м") == (340.0, STATUS_SAME)


def test_shtuka_i_edinica():
    assert convert_price(15, "ед", "шт") == (15.0, STATUS_SAME)


def test_tysyacha_shtuk():
    """«1000 шт» — цена за тысячу: 8 400 ₽/1000 шт → 8,4 ₽/шт."""
    assert convert_price(8400, "1000 шт", "шт") == (8.4, STATUS_CONVERTED)


# ---------------------------------------------------------------------------
# Разное написание одной единицы — не расхождение
# ---------------------------------------------------------------------------

def test_raznoe_napisanie_kvadratnogo_metra():
    for written in ("м²", "кв.м", "кв. м", "М2"):
        assert convert_price(350, written, "м2") == (350.0, STATUS_SAME), written


def test_probely_i_registr_ne_schitayutsya_rashozhdeniem():
    assert convert_price(350, " Шт ", "шт") == (350.0, STATUS_SAME)


# ---------------------------------------------------------------------------
# Несводимые единицы: цену не берём
# ---------------------------------------------------------------------------

def test_meshok_v_kilogrammy_otvergaetsya():
    """Вес мешка неизвестен — угадывать нельзя, цену не берём."""
    price, status = convert_price(500, "мешок", "кг")
    assert status == STATUS_INCOMPATIBLE
    assert price is None


def test_shtuka_v_kvadratnye_metry_otvergaetsya():
    assert convert_price(900, "шт", "м2") == (None, STATUS_INCOMPATIBLE)


def test_komplekt_v_shtuki_otvergaetsya():
    """Сколько штук в комплекте — неизвестно."""
    assert convert_price(12000, "компл", "шт") == (None, STATUS_INCOMPATIBLE)


def test_kilogramm_v_litry_otvergaetsya():
    """Без плотности масса в объём не переводится."""
    assert convert_price(70, "кг", "л") == (None, STATUS_INCOMPATIBLE)


def test_raznye_neznakomye_edinicy_otvergayutsya():
    assert convert_price(700, "рулон", "мешок") == (None, STATUS_INCOMPATIBLE)


def test_odinakovye_neznakomye_edinicy_sovpadayut():
    """«мешок» и «мешок» — одно и то же, что бы это ни было."""
    assert convert_price(700, "мешок", "Мешок") == (700.0, STATUS_SAME)


# ---------------------------------------------------------------------------
# Единица не указана: возражать нечем
# ---------------------------------------------------------------------------

def test_pustaya_edinica_ceny_ne_meshaet():
    """В прайсе единицу не заполнили → цену берём как есть, без пометки."""
    assert convert_price(350, None, "м2") == (350.0, STATUS_UNKNOWN)
    assert convert_price(350, "", "м2") == (350.0, STATUS_UNKNOWN)


def test_pustaya_edinica_pozicii_ne_meshaet():
    assert convert_price(350, "м2", "") == (350.0, STATUS_UNKNOWN)


# ---------------------------------------------------------------------------
# Мусор вместо цены
# ---------------------------------------------------------------------------

def test_ceny_net():
    assert convert_price(None, "т", "кг") == (None, STATUS_CONVERTED)


def test_cena_ne_chislo():
    assert convert_price("нет данных", "т", "кг") == (None, STATUS_CONVERTED)


def test_ochen_malenkaya_cena_ne_okruglyaetsya_v_nol():
    """4 ₽/т — это 0,004 ₽/кг. Округление до копеек обнулило бы цену."""
    price, status = convert_price(4, "т", "кг")
    assert status == STATUS_CONVERTED
    assert price == 0.004


# ---------------------------------------------------------------------------
# compare_units — та же логика, но без цены
# ---------------------------------------------------------------------------

def test_compare_units_vozvrashchaet_koefficient():
    assert compare_units("т", "кг") == (STATUS_CONVERTED, 0.001)
    assert compare_units("м2", "м2") == (STATUS_SAME, 1.0)
    assert compare_units("мешок", "кг") == (STATUS_INCOMPATIBLE, None)


# ---------------------------------------------------------------------------
# Пометки для человека
# ---------------------------------------------------------------------------

def test_pometka_o_pereschete_nazyvaet_oba_chisla():
    note = converted_note(73770, "т", 73.77, "кг", "прайс")
    assert note.startswith(PRICE_CONVERTED_PREFIX)
    assert "73770" in note and "73,77" in note
    assert "т" in note and "кг" in note
    assert "прайс" in note


def test_pometka_o_nesovpadenii_nazyvaet_obe_edinicy():
    note = mismatch_note("мешок", "кг", "прайс")
    assert note.startswith(PRICE_UNIT_MISMATCH_PREFIX)
    assert "мешок" in note and "кг" in note


def test_pometka_dopisyvaetsya_k_sushchestvuyushchej():
    """Пометка комплекта материалов должна остаться первой: по её началу
    редактор подсвечивает строку."""
    existing = "Добавлено по норме: 10 × 1,05 = 10,5 м2. ГЭСН."
    result = append_note(existing, mismatch_note("мешок", "кг", "прайс"))
    assert result.startswith("Добавлено по норме")
    assert PRICE_UNIT_MISMATCH_PREFIX in result
    assert "; " in result


def test_pometka_na_pustoe_pole():
    note = mismatch_note("мешок", "кг", "прайс")
    assert append_note("", note) == note
    assert append_note(None, note) == note


def test_pometka_ne_dublitsya():
    """Повторная проверка той же сметы не должна плодить одинаковые пометки."""
    note = mismatch_note("мешок", "кг", "прайс")
    once = append_note("", note)
    assert append_note(once, note) == once
