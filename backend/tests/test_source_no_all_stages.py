"""Номер позиции исходной сметы живёт на всех стадиях, не только в перечне.

План: plans/2026-08-11-nomer-pozicii-na-vseh-stadiyah.md
"""
import io

import openpyxl
import pytest_asyncio
from sqlalchemy import delete

from app.models.estimate_version import EstimateVersion
from app.models.project import Project
from app.models.summary_estimate import SummaryEstimate
from app.models.task import Task
from app.models.workflow_card import WorkflowCard
from app.services.material_kits import expand_completeness_items
from app.utils.estimate_rows import items_to_rows, rows_to_items
from app.utils.source_numbers import SOURCE_NO_HEADER, attach_source_numbers
from app.utils.xlsx_cost_parser import extract_total_cost, parse_list_sheet
from app.utils.xlsx_exporter import generate_estimate_xlsx


def _est_item(name, *, source_no=None, qty=1.0, work=100.0, mat=None, type_="Работа"):
    item = {
        "type": type_, "name": name, "unit": "м2", "quantity": qty,
        "work_price": work, "material_price": mat,
        "price_list_name": "Прайс", "sources": "", "notes": "",
    }
    if source_no is not None:
        item["source_no"] = source_no
    return item


# ── Фаза 1. Полнота ──────────────────────────────────────────────────────────

def test_material_kit_rows_have_no_number():
    """Комплект по нормам расхода дописывает строки, которых в смете не было."""
    items = [
        {"type": "Работа", "name": "Устройство перегородок из ГКЛ в 2 слоя с двух сторон",
         "unit": "м2", "quantity": 10.0, "notes": "", "source_no": "5"},
    ]
    result = expand_completeness_items(items)
    assert result.added > 0

    work = next(it for it in result.items if it.get("type") == "Работа")
    assert work["source_no"] == "5"
    assert all(not it.get("source_no") for it in result.items if it.get("type") == "Материал")


# ── Фаза 2. Смета: поле сквозь строку ────────────────────────────────────────

def test_number_survives_item_row_round_trip():
    items = [_est_item("Пробивка гнезд", source_no="1"),
             _est_item("Заделка борозд", source_no="2а")]
    rows = items_to_rows(items)
    assert [r["source_no"] for r in rows] == ["1", "2а"]

    back = rows_to_items(rows)
    assert [it["source_no"] for it in back] == ["1", "2а"]


def test_row_without_number_gets_none():
    rows = items_to_rows([_est_item("Пробивка гнезд")])
    assert rows[0]["source_no"] is None


def test_uploaded_list_column_is_read():
    """Перечень скачали, положили в задачу сметы — номер читается из файла."""
    from app.services.excel_service import generate_list

    data = generate_list([
        {"type": "Работа", "name": "Пробивка гнезд", "unit": "м2",
         "quantity": 1, "notes": "", "source_no": "3"},
    ])
    items = parse_list_sheet(data)
    assert items[0]["source_no"] == "3"
    assert items[0]["name"] == "Пробивка гнезд"


# ── Фаза 3. Смета: колонка в файле ───────────────────────────────────────────

def _estimate_values(data: bytes, title: str = "Смета") -> list[list]:
    wb = openpyxl.load_workbook(io.BytesIO(data))
    return [list(row) for row in wb[title].iter_rows(values_only=True)]


def test_estimate_xlsx_adds_column_first():
    data, _ = generate_estimate_xlsx([
        _est_item("Пробивка гнезд", source_no="1"),
        _est_item("Смеси бетонные", type_="Материал", source_no=None, work=None, mat=50.0),
    ])
    values = _estimate_values(data)
    assert values[0][:3] == ["№ в исходной смете", "№", "Наименование"]
    assert len(values[0]) == 11
    assert values[1][:3] == [1, 1, "Пробивка гнезд"]
    assert values[2][:3] == [None, 2, "Смеси бетонные"]


def test_estimate_xlsx_keeps_ten_columns_without_numbers():
    """Номеров нет — нет и колонки: первой идёт порядковый номер, как до функции."""
    data, _ = generate_estimate_xlsx([_est_item("Пробивка гнезд")])
    values = _estimate_values(data)
    assert SOURCE_NO_HEADER not in values[0]
    assert values[1][:2] == [1, "Пробивка гнезд"]


def test_estimate_total_unchanged_by_new_column():
    """Колонка сдвигает таблицу, но не сумму контракта."""
    plain = [_est_item("Пробивка гнезд", qty=2.0, work=100.0),
             _est_item("Смеси", type_="Материал", qty=3.0, work=None, mat=50.0)]
    numbered = [dict(it, source_no=str(i + 1)) for i, it in enumerate(plain)]

    data_plain, total_plain = generate_estimate_xlsx(plain)
    data_numbered, total_numbered = generate_estimate_xlsx(numbered)

    assert total_plain == total_numbered
    assert extract_total_cost(data_plain) == extract_total_cost(data_numbered)
    assert float(extract_total_cost(data_numbered)) == total_numbered


def test_multisheet_estimate_keeps_numbers_and_summary():
    items = [
        dict(_est_item("Пробивка", source_no="1"), sheet="Раздел 1"),
        dict(_est_item("Заделка", source_no="1"), sheet="Раздел 2"),
    ]
    data, total = generate_estimate_xlsx(items)
    wb = openpyxl.load_workbook(io.BytesIO(data))
    assert "Итого по смете" in wb.sheetnames
    assert _estimate_values(data, "Раздел 1")[1][0] == 1
    assert float(extract_total_cost(data)) == total


# ── Фаза 4 (бэкенд-часть). Оптимизация и сводная наследуют номер ─────────────

@pytest_asyncio.fixture
async def estimate_card(db_session):
    """Проект → карточка → смета с рабочей версией: строка с номером «4» и без номера."""
    project = Project(name="Объект с номерами", owner_id=1)
    db_session.add(project)
    await db_session.flush()
    task = Task(
        owner_id=1, user_role="project_manager", task_type="ESTIMATE_FROM_LIST",
        status="completed", input_files=[], input_file_data=[], chat_history=[],
        project_id=str(project.id),
    )
    db_session.add(task)
    await db_session.flush()
    version = EstimateVersion(
        task_id=str(task.id), version_number=0, version_label="original",
        version_display_name="Исходная смета", file_slot="estimate",
        task_type="ESTIMATE_FROM_LIST",
        rows=items_to_rows([
            _est_item("Пробивка гнезд", source_no="4"),
            _est_item("Заделка борозд"),
        ]),
    )
    card = WorkflowCard(project_id=str(project.id), name="АР", stage="estimate",
                        estimate_task_id=str(task.id))
    db_session.add_all([version, card])
    await db_session.commit()

    ids = {"project": str(project.id), "card": str(card.id), "version": str(version.id),
           "task": str(task.id)}
    yield ids

    await db_session.rollback()
    await db_session.execute(delete(SummaryEstimate).where(SummaryEstimate.project_id == ids["project"]))
    await db_session.execute(delete(WorkflowCard).where(WorkflowCard.id == ids["card"]))
    await db_session.execute(delete(EstimateVersion).where(EstimateVersion.task_id == ids["task"]))
    await db_session.execute(delete(Task).where(Task.id == ids["task"]))
    await db_session.execute(delete(Project).where(Project.id == ids["project"]))
    await db_session.commit()


async def test_summary_section_snapshot_keeps_number(async_client, user_token, estimate_card):
    """Раздел сводной, собранный из сметы карточки, несёт номер исходной позиции."""
    resp = await async_client.post(
        f"/api/projects/{estimate_card['project']}/summary",
        json={"sections": [{"card_id": estimate_card["card"],
                            "version_id": estimate_card["version"]}]},
        headers={"Authorization": user_token},
    )
    assert resp.status_code == 201, resp.text

    reread = await async_client.get(
        f"/api/projects/{estimate_card['project']}/summary",
        headers={"Authorization": user_token},
    )
    (section,) = reread.json()["sections"]
    assert [(r["name"], r.get("source_no")) for r in section["rows"]] == [
        ("Пробивка гнезд", "4"), ("Заделка борозд", None),
    ]


def test_end_to_end_list_to_estimate_file():
    """Перечень → полнота → смета: номер доезжает до файла сметы."""
    from_list = [
        {"type": "Работа", "name": "Устройство перегородок ГКЛ",
         "unit": "м2", "quantity": 10.0, "notes": "", "source_no": "5"},
        {"type": "Работа", "name": "Штукатурка откосов",
         "unit": "м2", "quantity": 4.0, "notes": "", "source_no": "6"},
    ]
    # Полнота: ИИ вернул те же работы и дописал материал
    after_ai = [
        {"type": "Работа", "name": "Устройство перегородок ГКЛ",
         "unit": "м2", "quantity": 10.0, "notes": ""},
        {"type": "Материал", "name": "Профиль ПН-2 50х40",
         "unit": "м", "quantity": 8.4, "notes": "добавлен по ГЭСН"},
        {"type": "Работа", "name": "Штукатурка откосов",
         "unit": "м2", "quantity": 4.0, "notes": ""},
    ]
    attach_source_numbers(after_ai, from_list)

    # Смета: цены проставлены, позиции пересобраны в строки версии
    priced = [dict(it, work_price=100.0, material_price=None,
                   price_list_name="Прайс", sources="") for it in after_ai]
    rows = items_to_rows(priced)
    assert [r["source_no"] for r in rows] == ["5", None, "6"]

    data, _ = generate_estimate_xlsx(rows_to_items(rows))
    values = _estimate_values(data)
    assert values[0][0] == "№ в исходной смете"
    assert [row[0] for row in values[1:4]] == [5, None, 6]


def test_optimizer_column_mapping_ignores_new_column():
    """Разбор сметы для оптимизации ищет колонки по названиям — наша не мешает.

    Колонка «№ в исходной смете» сдвигает таблицу на одну вправо: разбор по
    позиции колонок прочёл бы номер как наименование, а наименование — как
    единицу.
    """
    from app.utils.xlsx_optimizer import parse_estimate_xlsx

    data, _ = generate_estimate_xlsx([
        _est_item("Пробивка гнезд", source_no="1", qty=3.0, work=100.0),
        _est_item("Смеси бетонные", type_="Материал", source_no="2", qty=2.0,
                  work=None, mat=50.0),
    ])

    items = parse_estimate_xlsx(data)

    assert [(it["name"], it["unit"], it["quantity"], it["price_excl_vat"]) for it in items] == [
        ("Пробивка гнезд", "м2", 3.0, 100.0),
        ("Смеси бетонные", "м2", 2.0, 50.0),
    ]
