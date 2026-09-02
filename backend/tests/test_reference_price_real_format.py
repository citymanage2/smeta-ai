"""Эталонный прайс: формат реальной сводной сметы (РЖД, Техническая 87).

Фаза 6 плана `plans/2026-09-02-etalonnyy-prays-iz-smety.md`.

Файл пользователя вскрыл шесть расхождений с первым разбором, и каждое из них
молча портило бы прайс:

- позиции лежат на **двенадцати** листах-разделах, а рядом есть служебные листы
  («Сводная», «Целевые показатели») с теми же словами в шапке;
- шапка называется «Цена за ед. изм. Работы», а не «Цена работы»;
- под шапкой идёт строка нумерации колонок «1, 2, 3…»;
- у части строк заполнены **обе** цены — это материал, которому заодно
  посчитали монтаж;
- в колонке «Стоимость» лежит сумма за позицию, а не цена за единицу;
- одна и та же позиция встречается в файле с разными ценами.
"""
import io

import openpyxl
import pytest

from app.services import reference_price
from app.services.price_bulk import SKIP_NO_PRICE

# Шапка реального файла: строка 8, под ней — строка нумерации колонок.
_REAL_HEADERS = [
    "№ п/п", "Наименование работ", "Ед.\n изм.", "Кол-во",
    "Цена за ед. изм. Работы", "Цена за ед. изм. Материала",
    "Стоимость Материала руб.", "Стоимость работ руб.",
    "Общая стоимость, \n в т.ч. НДС, руб.", "Примечание",
]
_COLUMN_NUMBERS = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]


def _book(sheets: dict[str, list[list]]) -> bytes:
    """Книга «как настоящая»: шапка на восьмой строке, нумерация — на девятой."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for title, rows in sheets.items():
        ws = wb.create_sheet(title)
        for row in rows:
            ws.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _section_sheet(rows: list[list]) -> list[list]:
    head: list[list] = [[] for _ in range(7)]
    return head + [_REAL_HEADERS, _COLUMN_NUMBERS] + rows


def _row(name, unit=None, qty=None, price_work=None, price_material=None,
         cost_material=None, cost_work=None):
    return [None, name, unit, qty, price_work, price_material,
            cost_material, cost_work, None, None]


def test_reads_every_section_sheet():
    """Позиции лежат на разных листах — берём все, а не первый попавшийся."""
    data = _book({
        "Кровля": _section_sheet([_row("Кликфальц Pro", "м2", 932.36, None, 1760)]),
        "ЭОМ": _section_sheet([_row("Прокладка кабеля", "м", 100, 120, None)]),
    })

    result = reference_price.parse_reference_file(data, "сводная.xlsx", None)

    assert [(i["kind"], i["name"], i["price"]) for i in result["items"]] == [
        ("material", "Кликфальц Pro", 1760.0),
        ("work", "Прокладка кабеля", 120.0),
    ]


def test_service_sheets_are_ignored_whole():
    """«Сводная» и «Целевые показатели» — не про цены за единицу.

    В их шапке тоже есть «Наименование», а в строках — «Работы», «Материалы»,
    «Накладные» с многомиллионными суммами. Попади они в прайс — там появилась
    бы позиция «Работы» по 54 миллиона за штуку.
    """
    summary = [
        ["№", "Наименование", "% /\nКол-во", "Стоимость с НДС", "Стоимость без НДС"],
        [1.0, "Работы", None, 54369946.18, 44565529.65],
        [2.0, "Материалы", None, 55783959.89, 45724557.29],
    ]
    data = _book({
        "Сводная": summary,
        "Кровля": _section_sheet([_row("Кликфальц Pro", "м2", 932.36, None, 1760)]),
    })

    result = reference_price.parse_reference_file(data, "сводная.xlsx", None)

    assert [i["name"] for i in result["items"]] == ["Кликфальц Pro"]
    assert result["skipped"] == {}


def test_column_numbers_row_is_not_a_position():
    """Строка «1, 2, 3…» под шапкой — разметка листа, а не позиция с ценой 5."""
    data = _book({
        "Кровля": _section_sheet([_row("Кликфальц Pro", "м2", 932.36, None, 1760)]),
    })

    result = reference_price.parse_reference_file(data, "сводная.xlsx", None)

    assert [i["name"] for i in result["items"]] == ["Кликфальц Pro"]


def test_cost_column_is_not_a_price():
    """«Стоимость» — сумма за всю позицию. Взять её ценой за единицу значит
    завысить прайс во столько раз, сколько было объёма."""
    data = _book({
        "Смета": [
            ["Наименование", "Ед. изм.", "Кол-во", "Стоимость работ руб."],
            ["Кладка стен", "м3", 10, 12000],
        ],
    })

    with pytest.raises(reference_price.ReferenceFileError):
        reference_price.parse_reference_file(data, "смета.xlsx", "work")


def test_row_with_both_prices_is_a_material():
    """Кабель с ценой монтажа — это материал.

    Названия работы в такой строке нет: в колонке написан кабель. Записать по
    ней работу значило бы завести в прайсе работ позицию «Кабель витая пара».
    """
    data = _book({
        "ОПС": _section_sheet([
            _row("Кабель витая пара U/UTP 4х2х0,52", "м", 100, 120, 45),
        ]),
    })

    result = reference_price.parse_reference_file(data, "сводная.xlsx", None)

    assert [(i["kind"], i["price"]) for i in result["items"]] == [("material", 45.0)]
    assert result["notes"][reference_price.NOTE_BOTH_PRICES] == 1


def test_same_position_with_different_prices_is_reported():
    """Файл сам себе противоречит — человек обязан это увидеть.

    Эталон объявляет единственно верную цену; молча взять последнюю из двух
    разных значит выбрать за пользователя, какая из них верная.
    """
    data = _book({
        "ОПС": _section_sheet([
            _row("Кабель витая пара", "м", 10, None, 45),
            _row("Кабель витая пара", "м", 10, None, 44),
        ]),
    })

    result = reference_price.parse_reference_file(data, "сводная.xlsx", None)

    assert [(i["name"], i["price"]) for i in result["items"]] == [("Кабель витая пара", 44.0)]
    assert result["notes"][reference_price.NOTE_PRICE_CONFLICT] == 1


def test_same_position_with_same_price_is_not_a_conflict():
    """Повтор той же цены противоречием не является — предупреждать не о чем."""
    data = _book({
        "ОПС": _section_sheet([
            _row("Труба ПВХ", "м", 10, None, 18),
            _row("Труба ПВХ", "м", 20, None, 18),
        ]),
    })

    result = reference_price.parse_reference_file(data, "сводная.xlsx", None)

    assert len(result["items"]) == 1
    assert reference_price.NOTE_PRICE_CONFLICT not in result["notes"]


def test_rows_without_price_are_counted():
    """Раздел и позиция без цены — это «пропущено», а не потеря."""
    data = _book({
        "Кровля": _section_sheet([
            _row("Раздел 1. Ремонт кровли"),
            _row("Разборка покрытий кровель", "м2", 847.6),
            _row("Кликфальц Pro", "м2", 932.36, None, 1760),
        ]),
    })

    result = reference_price.parse_reference_file(data, "сводная.xlsx", None)

    assert [i["name"] for i in result["items"]] == ["Кликфальц Pro"]
    assert result["skipped"] == {SKIP_NO_PRICE: 2}


def test_whole_real_file_fits_the_limit():
    """Реальная сводная — это полторы тысячи позиций, и она должна проходить."""
    rows = [
        _row(f"Позиция {i}", "м2", 1, None, 100 + i)
        for i in range(1400)
    ]
    data = _book({"АР": _section_sheet(rows)})

    result = reference_price.parse_reference_file(data, "сводная.xlsx", None)

    assert len(result["items"]) == 1400


def test_similar_names_stay_separate_positions():
    """Шесть разных планок кровли — шесть позиций прайса, а не одна.

    Общая для проекта `normalize_name` сжимает «буква + слова + число» до
    марки материала: «Планка карнизная фальц 0,5 Satin Matt RAL 6005» и
    «Планка ендовы нижняя 0,5 Satin Matt RAL 6005» дают один и тот же ключ
    «п0,5 s6005». Для подбора цены это её собственная беда, а вот эталону
    таким ключом пользоваться нельзя: он записал бы одну позицию вместо шести
    и потерял бы пять цен из файла пользователя.
    """
    data = _book({
        "Кровля": _section_sheet([
            _row("Планка карнизная фальц 0,5 Satin Matt RAL 6005", "м", 124.8, None, 361),
            _row("Планка ендовы нижняя 0,5 Satin Matt RAL 6005", "м", 36.0, None, 1420),
            _row("Планка капельник 0,5 Satin Matt RAL 6005", "м", 124.8, None, 322),
        ]),
    })

    result = reference_price.parse_reference_file(data, "сводная.xlsx", None)

    assert sorted(i["price"] for i in result["items"]) == [322.0, 361.0, 1420.0]
    assert reference_price.NOTE_PRICE_CONFLICT not in result["notes"]


def test_case_and_spaces_still_mean_the_same_position():
    """Регистр и лишние пробелы позицию не удваивают — это одно и то же."""
    data = _book({
        "Кровля": _section_sheet([
            _row("Профиль ПН 75×50х3000", "шт", 10, None, 300),
            _row("профиль  пн  75×50х3000", "шт", 10, None, 300),
        ]),
    })

    result = reference_price.parse_reference_file(data, "сводная.xlsx", None)

    assert len(result["items"]) == 1


def test_conflicting_prices_are_listed_by_name():
    """Счётчика мало: человек должен видеть, у какой позиции какие цены разошлись.

    В реальном файле таких позиций 46 — «Демонтаж кабеля» по 30, 60 и 100 ₽.
    Эталон объявляет единственно верную цену, поэтому выбор между ними — не
    дело системы.
    """
    data = _book({
        "ЭОМ": _section_sheet([
            _row("Демонтаж кабеля", "м", 10, 30, None),
            _row("Демонтаж кабеля", "м", 10, 60, None),
            _row("Демонтаж кабеля", "м", 10, 100, None),
            _row("Штукатурка", "м2", 5, 400, None),
        ]),
    })

    result = reference_price.parse_reference_file(data, "сводная.xlsx", None)

    assert len(result["conflicts"]) == 1
    conflict = result["conflicts"][0]
    assert conflict["name"] == "Демонтаж кабеля"
    assert conflict["kind"] == "work"
    assert conflict["prices"] == [30.0, 60.0, 100.0]
    assert conflict["taken"] == 100.0


# ---------------------------------------------------------------------------
# Разведение одноимённых позиций по разделам
#
# Решение пользователя 02.09.2026: «там разные кабели — СОТ видеонаблюдение,
# ОПС пожарка и прочее, нужно как-то их развести». Лист сводной — это система,
# и одноимённая работа в разных системах стоит по-разному не по ошибке.
# ---------------------------------------------------------------------------

def test_same_name_in_different_sections_becomes_two_positions():
    """«Демонтаж кабеля» в ОПС и в СОТ — две разные работы, а не спор о цене."""
    data = _book({
        "ОПС": _section_sheet([_row("Демонтаж кабеля", "м", 10, 60, None)]),
        "СОТ": _section_sheet([_row("Демонтаж кабеля", "м", 10, 100, None)]),
    })

    result = reference_price.parse_reference_file(data, "сводная.xlsx", None)

    assert sorted((i["name"], i["price"]) for i in result["items"]) == [
        ("Демонтаж кабеля (ОПС)", 60.0),
        ("Демонтаж кабеля (СОТ)", 100.0),
    ]
    assert result["conflicts"] == []


def test_same_name_same_price_in_two_sections_stays_one_position():
    """Цена совпала — значит это и правда одна позиция. Плодить не за что."""
    data = _book({
        "ОПС": _section_sheet([_row("Труба ПВХ 20 мм", "м", 10, None, 18)]),
        "ЛВС": _section_sheet([_row("Труба ПВХ 20 мм", "м", 20, None, 18)]),
    })

    result = reference_price.parse_reference_file(data, "сводная.xlsx", None)

    assert [(i["name"], i["price"]) for i in result["items"]] == [("Труба ПВХ 20 мм", 18.0)]


def test_conflict_inside_one_section_is_still_reported():
    """Внутри одного раздела разделять нечем — это по-прежнему вопрос к человеку."""
    data = _book({
        "АР": _section_sheet([
            _row("Окраска стен", "м2", 10, 350, None),
            _row("Окраска стен", "м2", 10, 650, None),
        ]),
    })

    result = reference_price.parse_reference_file(data, "сводная.xlsx", None)

    assert [i["name"] for i in result["items"]] == ["Окраска стен"]
    assert result["conflicts"][0]["prices"] == [350.0, 650.0]


def test_single_sheet_file_gets_no_section_suffix():
    """Один лист — раздел ничего не уточняет, и в названии ему не место."""
    data = _book({
        "Смета": _section_sheet([_row("Окраска стен", "м2", 10, 350, None)]),
    })

    result = reference_price.parse_reference_file(data, "сводная.xlsx", None)

    assert result["items"][0]["name"] == "Окраска стен"
