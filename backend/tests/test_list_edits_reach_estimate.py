"""Правки перечня и полноты доезжают до сметы.

Смета со стадии «Исходный перечень» / «После проверки полноты» строится из
`task.progress_data['items']`. Пока сохранение строк туда не писало, поправленный
в редакторе объём оставался в документе и в скачиваемом файле, а в смету уезжал
перечень до правок — молча.
"""
import sys
import uuid
from unittest.mock import MagicMock

import pytest

sys.modules.setdefault('fitz', MagicMock())

from app.models.estimate_version import EstimateVersion  # noqa: E402
from app.models.project import Project  # noqa: E402
from app.models.task import Task  # noqa: E402
from app.models.user import User  # noqa: E402
from app.utils.auth import hash_password  # noqa: E402
from app.utils.generic_items import generic_rows_to_items  # noqa: E402


def _row(name: str, qty, type_: str = "Материал", notes: str = "", sheet=None) -> dict:
    row = {
        "row_id": str(uuid.uuid4()),
        "cells": {
            "Тип": type_,
            "Наименование": name,
            "Ед. изм": "м2",
            "Кол-во": qty,
            "Примечание": notes,
        },
    }
    if sheet is not None:
        row["sheet"] = sheet
    return row


# ── разбор строк документа ───────────────────────────────────────────────────

def test_rows_become_items():
    items = generic_rows_to_items([
        _row("Устройство перегородок из ГВЛ", 5.475, type_="Работа"),
        _row("Лист гипсоволокнистый ГВЛ 12,5 мм", 21.9, notes="Добавлено по норме: …"),
    ])
    assert items == [
        {"type": "Работа", "name": "Устройство перегородок из ГВЛ", "unit": "м2",
         "quantity": 5.475, "notes": ""},
        {"type": "Материал", "name": "Лист гипсоволокнистый ГВЛ 12,5 мм", "unit": "м2",
         "quantity": 21.9, "notes": "Добавлено по норме: …"},
    ]


def test_sheet_survives_the_trip():
    items = generic_rows_to_items([_row("Работа", 1, type_="Работа", sheet="Раздел 2")])
    assert items[0]["sheet"] == "Раздел 2"


def test_quantity_as_text_becomes_none():
    """«по проекту» в колонке количества числом не станет — как и при разборе xlsx."""
    items = generic_rows_to_items([_row("Позиция", "по проекту")])
    assert items[0]["quantity"] is None


def test_comma_decimal_is_read():
    items = generic_rows_to_items([_row("Позиция", "21,9")])
    assert items[0]["quantity"] == 21.9


def test_row_without_name_is_skipped():
    assert generic_rows_to_items([_row("", 5)]) == []


def test_rows_without_list_columns_give_nothing():
    """Строки чужого формата не должны превращаться в мусорные позиции."""
    assert generic_rows_to_items([{"row_id": "1", "cells": {"Что-то": "значение"}}]) == []


def test_round_trip_through_the_real_file():
    """Позиции → xlsx перечня → строки документа → снова позиции.

    Колонки документа приходят из настоящего файла, а не из фикстуры: разойдись
    их названия с разбором — правки в редакторе перестали бы доезжать до сметы
    молча, и ни один модульный тест этого бы не заметил.
    """
    from app.services.excel_service import data_sheet_titles, generate_list
    from app.utils.xlsx_generic import parse_xlsx_to_generic_rows

    items = [
        {"type": "Работа", "name": "Устройство перегородок из ГВЛ",
         "unit": "м2", "quantity": 5.475, "notes": ""},
        {"type": "Материал", "name": "Лист гипсоволокнистый ГВЛ 12,5 мм",
         "unit": "м2", "quantity": 21.9,
         "notes": "Добавлено по норме: 5,475 × 4 (2 слоя × 2 стороны) = 21,9 м2."},
    ]
    xlsx = generate_list(items)
    rows = parse_xlsx_to_generic_rows(xlsx, sheets=data_sheet_titles(items))
    restored = generic_rows_to_items(rows)

    assert [(i["type"], i["name"], i["unit"], i["quantity"]) for i in restored] == [
        (i["type"], i["name"], i["unit"], i["quantity"]) for i in items
    ]
    assert restored[1]["notes"].startswith("Добавлено по норме")


def _doc(svc, task, version, file_slot: str):
    """Документ проверки полноты вокруг задачи и её версии."""
    return svc.ResolvedDocument(
        card=None, kind="completeness", task=task, project=None,
        file_slot=file_slot, row_format="generic", versions=[version],
        active=version,
    )


# ── сохранение документа обновляет позиции задачи ────────────────────────────

@pytest.fixture
async def list_task_env(db_session, fake_s3):
    for model in (EstimateVersion, Task, Project, User):
        await db_session.execute(model.__table__.delete())
    await db_session.commit()

    user = User(username="pm-list", role="project_manager", full_name="Иванов Иван",
                password_hash=hash_password("p1"))
    db_session.add(user)
    await db_session.flush()

    project = Project(name="Объект", owner_id=user.id)
    db_session.add(project)
    await db_session.flush()

    task = Task(
        owner_id=user.id, user_role="project_manager",
        task_type="CHECK_LIST_COMPLETENESS", status="completed",
        input_files=[], input_file_data=[], chat_history=[],
        project_id=str(project.id),
        progress_data={"items": [
            {"type": "Работа", "name": "Устройство перегородок из ГВЛ",
             "unit": "м2", "quantity": 5.475, "notes": ""},
        ]},
    )
    db_session.add(task)
    await db_session.flush()

    version = EstimateVersion(
        task_id=str(task.id), version_number=0, version_label="original",
        version_display_name="V0 — Оригинал",
        rows=[_row("Устройство перегородок из ГВЛ", 5.475, type_="Работа")],
        file_slot="result", task_type="CHECK_LIST_COMPLETENESS",
    )
    db_session.add(version)
    await db_session.commit()

    return {"user_id": user.id, "task_id": str(task.id), "version_id": str(version.id)}


@pytest.mark.asyncio
async def test_saved_rows_update_task_items(db_session, list_task_env):
    """Человек дописал материал в редакторе — смета обязана его увидеть."""
    from app.services import document_service as svc

    task = await db_session.get(Task, list_task_env["task_id"])
    version = await db_session.get(EstimateVersion, list_task_env["version_id"])
    doc = _doc(svc, task, version, file_slot="result")

    new_rows = [
        _row("Устройство перегородок из ГВЛ", 5.475, type_="Работа"),
        _row("Лист гипсоволокнистый ГВЛ 12,5 мм", 21.9,
             notes="Добавлено по норме: 5,475 × 4 (2 слоя × 2 стороны) = 21,9 м2."),
    ]
    svc._sync_task_items(doc, new_rows)

    items = task.progress_data["items"]
    assert len(items) == 2
    assert items[1]["name"] == "Лист гипсоволокнистый ГВЛ 12,5 мм"
    assert items[1]["quantity"] == 21.9


@pytest.mark.asyncio
async def test_rows_of_foreign_format_do_not_wipe_task_items(db_session, list_task_env):
    """Пустой разбор не должен стирать позиции задачи."""
    from app.services import document_service as svc

    task = await db_session.get(Task, list_task_env["task_id"])
    version = await db_session.get(EstimateVersion, list_task_env["version_id"])
    doc = _doc(svc, task, version, file_slot="result")
    before = list(task.progress_data["items"])

    svc._sync_task_items(doc, [{"row_id": "1", "cells": {"Колонка": "значение"}}])

    assert task.progress_data["items"] == before


@pytest.mark.asyncio
async def test_input_file_document_does_not_touch_task_items(db_session, list_task_env):
    """Файл заказчика — только для просмотра: позиции задачи он не переписывает."""
    from app.services import document_service as svc

    task = await db_session.get(Task, list_task_env["task_id"])
    version = await db_session.get(EstimateVersion, list_task_env["version_id"])
    doc = _doc(svc, task, version, file_slot="input")
    before = list(task.progress_data["items"])

    svc._sync_task_items(doc, [_row("Чужая строка", 1)])

    assert task.progress_data["items"] == before
