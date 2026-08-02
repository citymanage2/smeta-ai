"""Выгрузка-ведомость: любой документ → xlsx по заданной настройке.

Фаза 9 плана `plans/2026-08-02-edinyy-redaktor-tablic.md`.

Раньше конструктор выгрузки был только у сводной. Теперь он общий: столбцы
приходят от документа (у перечня — свои, у сметы — свои), строки приходят из
предпросмотра (человек мог их поправить), шапка настраивается.

Цены в выгрузку идут с коэффициентом (решение пользователя 4.5) — они уже
умножены на стороне редактора, поэтому сервер их не трогает и не множит второй
раз.
"""
import io

import openpyxl
import pytest
import pytest_asyncio

from app.models.estimate_version import EstimateVersion
from app.models.history import TaskHistory
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.models.workflow_card import WorkflowCard
from app.utils.auth import create_access_token, hash_password


def _auth(user_id: int, role: str) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id, role)}"}


ESTIMATE_COLUMNS = [
    {"key": "num", "label": "№", "numeric": True},
    {"key": "name", "label": "Наименование", "numeric": False},
    {"key": "unit", "label": "Ед. изм.", "numeric": False},
    {"key": "qty", "label": "Кол-во", "numeric": True},
    {"key": "price_work", "label": "Цена работ", "numeric": True},
    {"key": "cost_work", "label": "Стоим. работ", "numeric": True},
]

EXPORT_ROWS = [
    {"num": 1, "name": "Кладка стен", "unit": "м3", "qty": 4,
     "price_work": 1050, "cost_work": 4200},
    {"num": 2, "name": "Штукатурка", "unit": "м2", "qty": 10,
     "price_work": 525, "cost_work": 5250},
]


@pytest_asyncio.fixture
async def export_env(db_session, fake_s3):
    for model in (EstimateVersion, TaskHistory, WorkflowCard, Task, Project, User):
        await db_session.execute(model.__table__.delete())
    await db_session.commit()

    pm1 = User(username="pm1", role="project_manager", full_name="Иванов Иван",
               password_hash=hash_password("p1"))
    pm2 = User(username="pm2", role="project_manager", full_name="Петров Пётр",
               password_hash=hash_password("p2"))
    db_session.add_all([pm1, pm2])
    await db_session.flush()

    project = Project(name="ЖК Северный", owner_id=pm1.id)
    db_session.add(project)
    await db_session.flush()

    task = Task(
        owner_id=pm1.id, user_role="project_manager", task_type="ESTIMATE_FROM_LIST",
        status="completed", input_files=[], input_file_data=[], chat_history=[],
        project_id=str(project.id),
    )
    db_session.add(task)
    await db_session.flush()

    db_session.add(EstimateVersion(
        task_id=str(task.id), version_number=0, version_label="original",
        version_display_name="Смета", rows=[], file_slot="estimate",
        task_type="ESTIMATE_FROM_LIST",
    ))
    card = WorkflowCard(project_id=str(project.id), name="АР", stage="estimate",
                        estimate_task_id=str(task.id))
    db_session.add(card)
    await db_session.commit()

    env = {"pm1": pm1.id, "pm2": pm2.id, "card_id": str(card.id),
           "project_id": str(project.id), "task_id": str(task.id)}
    yield env

    for model in (EstimateVersion, TaskHistory, WorkflowCard, Task, Project, User):
        await db_session.execute(model.__table__.delete())
    await db_session.commit()


def _sheet(content: bytes):
    return openpyxl.load_workbook(io.BytesIO(content)).active


def _cells(ws) -> list:
    return [[c.value for c in row] for row in ws.iter_rows()]


async def _export(async_client, env, body: dict, user: str = "pm1"):
    return await async_client.post(
        f"/documents/{env['card_id']}/estimate/export",
        json=body, headers=_auth(env[user], "project_manager"),
    )


@pytest.mark.asyncio
async def test_export_returns_selected_columns_in_order(async_client, export_env):
    resp = await _export(async_client, export_env, {
        "columns": [ESTIMATE_COLUMNS[1], ESTIMATE_COLUMNS[5]],
        "rows": EXPORT_ROWS,
        "header": {"title": "Ведомость работ"},
    })
    assert resp.status_code == 200, resp.text

    rows = _cells(_sheet(resp.content))
    header_row = next(r for r in rows if r and r[0] == "Наименование")
    assert header_row[:2] == ["Наименование", "Стоим. работ"]
    assert ["Кладка стен", 4200] in [r[:2] for r in rows]


@pytest.mark.asyncio
async def test_export_header_is_configurable(async_client, export_env):
    with_header = await _export(async_client, export_env, {
        "columns": ESTIMATE_COLUMNS,
        "rows": EXPORT_ROWS,
        "header": {
            "title": "Ведомость работ", "object_name": "Объект: корпус 1",
            "project_name": "ЖК Северный", "show_date": True, "show_total": True,
        },
    })
    text = " ".join(
        str(c) for row in _cells(_sheet(with_header.content)) for c in row if c
    )
    assert "Ведомость работ" in text
    assert "корпус 1" in text
    assert "ЖК Северный" in text

    without = await _export(async_client, export_env, {
        "columns": ESTIMATE_COLUMNS,
        "rows": EXPORT_ROWS,
        "header": {
            "title": "Ведомость работ", "object_name": "Объект: корпус 1",
            "project_name": "ЖК Северный", "show_date": False, "show_total": False,
        },
    })
    plain = " ".join(
        str(c) for row in _cells(_sheet(without.content)) for c in row if c
    )
    assert "ИТОГО" not in plain


@pytest.mark.asyncio
async def test_export_total_row_sums_money_not_quantity(async_client, export_env):
    resp = await _export(async_client, export_env, {
        "columns": ESTIMATE_COLUMNS,
        "rows": EXPORT_ROWS,
        "header": {"title": "Ведомость работ", "show_total": True},
    })
    rows = _cells(_sheet(resp.content))
    total_row = next(r for r in rows if r and str(r[0] or "").startswith("ИТОГО"))

    # Позиции столбцов: №, Наименование, Ед. изм., Кол-во, Цена работ, Стоим. работ
    assert total_row[5] == pytest.approx(9450.0)   # стоимости складываются
    assert total_row[3] is None                    # «Кол-во» не складывается
    assert total_row[4] is None                    # цена за единицу тоже


@pytest.mark.asyncio
async def test_export_accepts_any_columns_of_the_document(async_client, export_env):
    """У перечня свои колонки — генератор не знает заранее ни одной из них."""
    resp = await _export(async_client, export_env, {
        "columns": [
            {"key": "Обоснование", "label": "Обоснование", "numeric": False},
            {"key": "Объём работ", "label": "Объём работ", "numeric": True},
        ],
        "rows": [{"Обоснование": "ГЭСН 8-1-1", "Объём работ": 12}],
        "header": {"title": "Перечень"},
    })
    assert resp.status_code == 200, resp.text
    text = " ".join(
        str(c) for row in _cells(_sheet(resp.content)) for c in row if c
    )
    assert "ГЭСН 8-1-1" in text
    assert "Обоснование" in text


@pytest.mark.asyncio
async def test_export_without_rows_is_rejected(async_client, export_env):
    resp = await _export(async_client, export_env, {
        "columns": ESTIMATE_COLUMNS, "rows": [], "header": {"title": "Пусто"},
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_export_of_foreign_document_forbidden(async_client, export_env):
    resp = await _export(async_client, export_env, {
        "columns": ESTIMATE_COLUMNS, "rows": EXPORT_ROWS, "header": {},
    }, user="pm2")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_export_available_in_readonly_document(async_client, db_session, export_env):
    """Выгрузка — чтение: она доступна и когда документ править нельзя."""
    task = await db_session.get(Task, export_env["task_id"])
    task.status = "processing"
    await db_session.commit()

    resp = await _export(async_client, export_env, {
        "columns": ESTIMATE_COLUMNS, "rows": EXPORT_ROWS,
        "header": {"title": "Ведомость работ"},
    })
    assert resp.status_code == 200, resp.text
