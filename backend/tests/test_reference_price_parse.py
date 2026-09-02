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
import pytest_asyncio
from sqlalchemy import delete, select

from app.models.price import PriceMaterial, PriceWork
from app.services import reference_price
from app.services.price_bulk import SKIP_NO_NAME, SKIP_NO_PRICE, SKIP_NOT_PRICEABLE
from app.utils.price_min import ESTIMATE_CONTRACTOR


@pytest_asyncio.fixture(autouse=True)
async def clean_price(db_session):
    """Пустой прайс до и после каждого теста.

    Тесты этого файла делают `commit`, а общая тестовая БД живёт весь прогон:
    без уборки позиция одного теста становилась бы «неожиданным совпадением»
    в другом — и файл проходил бы или падал в зависимости от порядка.
    """
    async def _wipe():
        await db_session.execute(delete(PriceWork))
        await db_session.execute(delete(PriceMaterial))
        await db_session.commit()

    await _wipe()
    yield
    await _wipe()


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
# План вытеснения
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_plan_shows_every_price_that_will_be_erased(db_session):
    """Главный экран решения: какие именно цены исчезнут и чьи они."""
    db_session.add(PriceWork(
        name="Кладка стен", unit="м3",
        prices={"ООО Рога": 1200.0, "ИП Копыта": 1100.0, ESTIMATE_CONTRACTOR: 900.0},
        min_price=900.0,
    ))
    await db_session.commit()

    plan = await reference_price.build_plan(db_session, [
        {"kind": "work", "name": "Кладка стен", "unit": "м3", "price": 1000.0},
    ])

    entry = plan[0]
    assert entry["action"] == reference_price.ACTION_REPRICE
    assert sorted(entry["removed"], key=lambda r: r["contractor"]) == [
        {"contractor": "ИП Копыта", "price": 1100.0},
        {"contractor": "ООО Рога", "price": 1200.0},
    ]
    # Цена «Из смет» тоже перезаписывается, но это не потеря чужой цены —
    # в списке на стирание ей не место.
    assert all(r["contractor"] != ESTIMATE_CONTRACTOR for r in entry["removed"])


@pytest.mark.asyncio
async def test_plan_marks_new_position_as_add(db_session):
    """Позиции в прайсе нет — стирать нечего, просто добавляем."""
    plan = await reference_price.build_plan(db_session, [
        {"kind": "work", "name": "Позиция которой нет", "unit": "м2", "price": 10.0},
    ])

    assert plan[0]["action"] == reference_price.ACTION_ADD
    assert plan[0]["removed"] == []
    assert plan[0]["match"] is None


@pytest.mark.asyncio
async def test_plan_blocks_incompatible_unit(db_session):
    """Цена подрядчика за мешок и цена из файла за кг — про разное. Не стираем."""
    db_session.add(PriceMaterial(name="Смесь сухая", unit="мешок", price=300.0))
    await db_session.commit()

    plan = await reference_price.build_plan(db_session, [
        {"kind": "material", "name": "Смесь сухая", "unit": "кг", "price": 12.0},
    ])

    entry = plan[0]
    assert entry["action"] == reference_price.ACTION_BLOCKED
    assert entry["reason"] == reference_price.BLOCK_UNIT_MISMATCH
    assert entry["removed"] == []


@pytest.mark.asyncio
async def test_plan_shows_material_price_that_will_be_replaced(db_session):
    """У материала цена одна — но человек должен видеть, какую он затирает."""
    db_session.add(PriceMaterial(name="Кирпич", unit="шт", price=30.0))
    await db_session.commit()

    plan = await reference_price.build_plan(db_session, [
        {"kind": "material", "name": "Кирпич", "unit": "шт", "price": 25.0},
    ])

    entry = plan[0]
    assert entry["action"] == reference_price.ACTION_REPRICE
    assert entry["removed"] == [{"contractor": None, "price": 30.0}]


@pytest.mark.asyncio
async def test_plan_does_not_touch_the_database(db_session):
    """Предпросмотр — это чтение. После него в прайсе ровно то же, что было."""
    db_session.add(PriceWork(
        name="Кладка стен", unit="м3", prices={"ООО Рога": 1200.0}, min_price=1200.0,
    ))
    await db_session.commit()

    await reference_price.build_plan(db_session, [
        {"kind": "work", "name": "Кладка стен", "unit": "м3", "price": 1000.0},
        {"kind": "material", "name": "Кирпич", "unit": "шт", "price": 25.0},
    ])

    db_session.expire_all()
    work = (await db_session.execute(select(PriceWork))).scalars().all()
    materials = (await db_session.execute(select(PriceMaterial))).scalars().all()
    assert len(work) == 1
    assert work[0].prices == {"ООО Рога": 1200.0}
    assert materials == []
