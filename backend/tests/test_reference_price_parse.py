"""Эталонный прайс: разбор файла и план вытеснения.

Фаза 1 плана `plans/2026-09-02-etalonnyy-prays-iz-smety.md`.

Здесь проверяется самое опасное место функции: что именно система собирается
стереть. Прайс общий на всех, удалённая цена подрядчика не восстанавливается,
поэтому план операции обязан быть предсказуемым до единицы измерения:

- цена за «100 м2» — это не цена за м2 (правило №3 плана, `unit_price_factor`);
- несводимые единицы (мешок ↔ кг) вытеснением не считаются вовсе: цена
  подрядчика назначена за другое (правило №8 CLAUDE.md);
- позиция без имени или без цены не пишется, а попадает в сводку «пропущено».
"""
import io

import openpyxl
import pytest

from app.services import reference_price
from app.services.price_bulk import SKIP_NO_NAME, SKIP_NO_PRICE, SKIP_NOT_PRICEABLE
from app.utils.price_min import ESTIMATE_CONTRACTOR


def _xlsx(rows: list[list]) -> bytes:
    """Книга из строк «как есть» — первая строка становится заголовком."""
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


_SMETA_HEADERS = [
    "№", "Тип", "Наименование", "Ед. изм.", "Кол-во",
    "Цена работы (за ед.)", "Цена материала (за ед.)",
    "Стоимость работ", "Стоимость материалов",
]


def _smeta_file(rows: list[list]) -> bytes:
    return _xlsx([_SMETA_HEADERS] + rows)


# ---------------------------------------------------------------------------
# Разбор файла
# ---------------------------------------------------------------------------

def test_smeta_format_gives_works_and_materials():
    """Файл сметы нашего формата — оба типа из одного файла, по колонке «Тип»."""
    data = _smeta_file([
        [1, "Работа", "Кладка стен", "м3", 4, 1000, None, 4000, None],
        [2, "Материал", "Кирпич", "шт", 400, None, 25, None, 10000],
    ])

    parsed = reference_price.parse_reference_file(data, "смета.xlsx", None)
    items, skipped = parsed["items"], parsed["skipped"]

    assert skipped == {}
    assert [(i["kind"], i["name"], i["unit"], i["price"]) for i in items] == [
        ("work", "Кладка стен", "м3", 1000.0),
        ("material", "Кирпич", "шт", 25.0),
    ]


def test_section_row_is_not_a_price():
    """Раздел — не работа и не материал: цены у него нет, в прайсе ему нечего делать."""
    data = _smeta_file([
        [1, "Раздел", "Отделочные работы", None, None, None, None, None, None],
        [2, "Работа", "Штукатурка", "м2", 10, 500, None, 5000, None],
    ])

    parsed = reference_price.parse_reference_file(data, "смета.xlsx", None)
    items, skipped = parsed["items"], parsed["skipped"]

    assert [i["name"] for i in items] == ["Штукатурка"]
    assert skipped == {SKIP_NOT_PRICEABLE: 1}


def test_multiplier_unit_becomes_base_price():
    """«100 м2» по 500 ₽ — это 5 ₽ за м2. Без пересчёта прайс завышен в сто раз."""
    data = _smeta_file([
        [1, "Работа", "Окраска", "100 м2", 1, 500, None, 500, None],
    ])

    parsed = reference_price.parse_reference_file(data, "смета.xlsx", None)
    items, skipped = parsed["items"], parsed["skipped"]

    assert items[0]["unit"] == "м2"
    assert items[0]["price"] == 5.0


def test_row_without_name_or_price_is_skipped_with_reason():
    """Молча терять строки нельзя: у каждой пропущенной есть причина."""
    data = _smeta_file([
        [1, "Работа", "", "м2", 1, 500, None, 500, None],
        [2, "Работа", "Штукатурка", "м2", 1, None, None, None, None],
        [3, "Материал", "Кирпич", "шт", 1, None, 0, None, 0],
    ])

    parsed = reference_price.parse_reference_file(data, "смета.xlsx", None)
    items, skipped = parsed["items"], parsed["skipped"]

    assert items == []
    assert skipped == {SKIP_NO_NAME: 1, SKIP_NO_PRICE: 2}


def test_simple_price_format_uses_selected_kind():
    """Таблица «Наименование / Ед. / Цена» — тип берётся из выбора человека."""
    data = _xlsx([
        ["Наименование", "Ед. изм.", "Цена"],
        ["Кирпич", "шт", 25],
    ])

    parsed = reference_price.parse_reference_file(data, "прайс.xlsx", "material")
    items, skipped = parsed["items"], parsed["skipped"]

    assert skipped == {}
    assert [(i["kind"], i["name"], i["price"]) for i in items] == [
        ("material", "Кирпич", 25.0),
    ]


def test_simple_format_without_kind_is_refused():
    """В простом файле типа нет: без выбора человека система его не выдумывает."""
    data = _xlsx([
        ["Наименование", "Ед. изм.", "Цена"],
        ["Кирпич", "шт", 25],
    ])

    with pytest.raises(reference_price.ReferenceFileError):
        reference_price.parse_reference_file(data, "прайс.xlsx", None)


def test_same_name_twice_keeps_the_last_price():
    """Одна позиция в прайсе одна: побеждает последняя строка файла."""
    data = _smeta_file([
        [1, "Работа", "Кладка стен", "м3", 1, 1000, None, 1000, None],
        [2, "Работа", "кладка  стен", "м3", 1, 1200, None, 1200, None],
    ])

    parsed = reference_price.parse_reference_file(data, "смета.xlsx", None)
    items, skipped = parsed["items"], parsed["skipped"]

    assert [(i["name"], i["price"]) for i in items] == [("кладка  стен", 1200.0)]


def test_too_many_items_refused_not_truncated():
    """Файл сверх потолка отклоняется целиком — обрезать молча нельзя."""
    rows = [
        [i, "Работа", f"Работа {i}", "м2", 1, 100 + i, None, None, None]
        for i in range(reference_price.MAX_REFERENCE_ITEMS + 1)
    ]

    with pytest.raises(reference_price.ReferenceFileError):
        reference_price.parse_reference_file(_smeta_file(rows), "смета.xlsx", None)


def test_file_without_name_column_is_refused():
    """Не разобрали файл — говорим об этом, а не пишем пустой прайс."""
    data = _xlsx([["Позиция", "Цена"], ["Кирпич", 25]])

    with pytest.raises(reference_price.ReferenceFileError):
        reference_price.parse_reference_file(data, "прайс.xlsx", "material")


# ---------------------------------------------------------------------------
# План вытеснения — то, что человек видит в предпросмотре
# ---------------------------------------------------------------------------

_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


async def _preview_plan(async_client, admin_token, rows: list[list]) -> list[dict]:
    """План из `/prices/reference/preview` для файла сметы с этими строками."""
    r = await async_client.post(
        "/prices/reference/preview",
        files={"file": ("смета.xlsx", _smeta_file(rows), _XLSX)},
        headers={"Authorization": admin_token},
    )
    assert r.status_code == 200, r.text
    return r.json()["plan"]


@pytest.mark.asyncio
async def test_plan_shows_every_price_that_will_be_erased(async_client, admin_token, price_db):
    """Главный экран решения: какие именно цены исчезнут и чьи они."""
    price_db.work(
        "Кладка стен", unit="м3",
        prices={"ООО Рога": 1200.0, "ИП Копыта": 1100.0, ESTIMATE_CONTRACTOR: 900.0},
    )
    await price_db.load()

    (entry,) = await _preview_plan(async_client, admin_token, [
        [1, "Работа", "Кладка стен", "м3", 1, 1000, None, 1000, None],
    ])

    assert entry["action"] == reference_price.ACTION_REPRICE
    assert sorted(entry["removed"], key=lambda r: r["contractor"]) == [
        {"contractor": "ИП Копыта", "price": 1100.0},
        {"contractor": "ООО Рога", "price": 1200.0},
    ]
    # Цена «Из смет» тоже перезаписывается, но это не потеря чужой цены —
    # в списке на стирание ей не место.
    assert all(r["contractor"] != ESTIMATE_CONTRACTOR for r in entry["removed"])


@pytest.mark.asyncio
async def test_plan_marks_new_position_as_add(async_client, admin_token, price_db):
    """Позиции в прайсе нет — стирать нечего, просто добавляем."""
    price_db.work("Кладка стен", unit="м3", prices={"ООО Рога": 1200.0})
    await price_db.load()

    (entry,) = await _preview_plan(async_client, admin_token, [
        [1, "Работа", "Позиция которой нет", "м2", 1, 10, None, 10, None],
    ])

    assert entry["action"] == reference_price.ACTION_ADD
    assert entry["removed"] == []
    assert entry["match"] is None


@pytest.mark.asyncio
async def test_plan_blocks_incompatible_unit(async_client, admin_token, price_db):
    """Цена подрядчика за мешок и цена из файла за кг — про разное. Не стираем."""
    price_db.material("Смесь сухая", unit="мешок", price=300.0)
    await price_db.load()

    (entry,) = await _preview_plan(async_client, admin_token, [
        [1, "Материал", "Смесь сухая", "кг", 1, None, 12, None, 12],
    ])

    assert entry["action"] == reference_price.ACTION_BLOCKED
    assert entry["reason"] == reference_price.BLOCK_UNIT_MISMATCH
    assert entry["removed"] == []


@pytest.mark.asyncio
async def test_plan_shows_material_price_that_will_be_replaced(async_client, admin_token, price_db):
    """У материала цена одна — но человек должен видеть, какую он затирает."""
    price_db.material("Кирпич", unit="шт", price=30.0)
    await price_db.load()

    (entry,) = await _preview_plan(async_client, admin_token, [
        [1, "Материал", "Кирпич", "шт", 1, None, 25, None, 25],
    ])

    assert entry["action"] == reference_price.ACTION_REPRICE
    assert entry["removed"] == [{"contractor": None, "price": 30.0}]
