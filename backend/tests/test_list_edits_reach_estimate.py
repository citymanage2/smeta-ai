"""Правки перечня и полноты доезжают до сметы.

Смета со стадии «Исходный перечень» / «После проверки полноты» строится из
`task.progress_data['items']`. Пока сохранение строк туда не писало, поправленный
в редакторе объём оставался в документе и в скачиваемом файле, а в смету уезжал
перечень до правок — молча.
"""
import uuid

import pytest
import pytest_asyncio

from app.models.document_lock import DocumentLock
from app.models.estimate_version import EstimateVersion
from app.models.history import TaskHistory
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.models.workflow_card import WorkflowCard
from app.utils.auth import create_access_token, hash_password
from app.utils.generic_items import generic_rows_to_items


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


# ── «Применить» в документе полноты обновляет позиции задачи ─────────────────

_MODELS = (DocumentLock, TaskHistory, EstimateVersion, WorkflowCard, Task, Project, User)

_PARTITION = _row("Устройство перегородок из ГВЛ", 5.475, type_="Работа")


@pytest_asyncio.fixture
async def completeness_env(db_session, fake_s3):
    """Карточка с посчитанной полнотой: позиции задачи и рабочая версия V0."""
    for model in _MODELS:
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

    card = WorkflowCard(project_id=str(project.id), name="АР", stage="completeness",
                        completeness_task_id=str(task.id))
    version = EstimateVersion(
        task_id=str(task.id), version_number=0, version_label="original",
        version_display_name="V0 — Оригинал", rows=[_PARTITION],
        file_slot="result", task_type="CHECK_LIST_COMPLETENESS",
    )
    db_session.add_all([card, version])
    await db_session.commit()

    yield {
        "headers": {"Authorization": f"Bearer {create_access_token(user.id, 'project_manager', 'pm-list')}"},
        "card_id": str(card.id), "task_id": str(task.id), "version_id": str(version.id),
    }

    for model in _MODELS:
        await db_session.execute(model.__table__.delete())
    await db_session.commit()


async def _apply(async_client, env, rows) -> None:
    r = await async_client.post(
        f"/documents/{env['card_id']}/completeness/apply",
        json={"version_id": env["version_id"], "rev": 0, "rows": rows},
        headers=env["headers"],
    )
    assert r.status_code == 200, r.text


async def _task_items(db_session, env) -> list[dict]:
    db_session.expire_all()
    task = await db_session.get(Task, env["task_id"])
    return task.progress_data["items"]


@pytest.mark.asyncio
async def test_saved_rows_update_task_items(async_client, db_session, completeness_env):
    """Человек дописал материал в редакторе — смета обязана его увидеть."""
    await _apply(async_client, completeness_env, [
        _PARTITION,
        _row("Лист гипсоволокнистый ГВЛ 12,5 мм", 21.9,
             notes="Добавлено по норме: 5,475 × 4 (2 слоя × 2 стороны) = 21,9 м2."),
    ])

    items = await _task_items(db_session, completeness_env)
    assert [(i["name"], i["quantity"]) for i in items] == [
        ("Устройство перегородок из ГВЛ", 5.475),
        ("Лист гипсоволокнистый ГВЛ 12,5 мм", 21.9),
    ]


@pytest.mark.asyncio
async def test_rows_of_foreign_format_do_not_wipe_task_items(async_client, db_session, completeness_env):
    """Пустой разбор не должен стирать позиции задачи."""
    before = await _task_items(db_session, completeness_env)

    await _apply(async_client, completeness_env, [{"row_id": "1", "cells": {"Колонка": "значение"}}])

    assert await _task_items(db_session, completeness_env) == before
