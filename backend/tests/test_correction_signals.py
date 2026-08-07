"""Журнал корректировок: «система посчитала X — человек поставил Y».

План: plans/2026-08-07-obuchenie-na-korrektirovkah.md, Фаза 1.

Проверяется ровно то, без чего журнал врёт: сигнал пишется только на ручную
правку, значение «было» берётся исходное (не с коэффициентом), повторная правка
той же ячейки помечается как не первая, а сбой журнала не отменяет сохранение
правки.
"""
import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.correction_signal import FIELD_ROW, CorrectionSignal
from app.models.document_lock import DocumentLock
from app.models.estimate_version import EstimateVersion
from app.models.history import TaskHistory
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.models.workflow_card import WorkflowCard
from app.utils.auth import create_access_token, hash_password


def _auth(user_id: int, role: str, username: str) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id, role, username)}"}


def _pm1(env: dict) -> dict:
    return _auth(env["pm1"], "project_manager", "pm1")


def _list_rows(price_work: int = 3000) -> list[dict]:
    """Строки перечня: generic-формат, поля — колонки исходного файла."""
    return [
        {
            "row_id": "r1",
            "cells": {"Тип": "Работа", "Наименование": "Разработка грунта",
                      "Ед. изм": "м3", "Кол-во": 27, "Цена работ": price_work},
        },
        {
            "row_id": "r2",
            "cells": {"Тип": "Материал", "Наименование": "Песок",
                      "Ед. изм": "м3", "Кол-во": 10, "Цена работ": 500},
        },
    ]


def _estimate_rows(price_work: float = 3000.0) -> list[dict]:
    return [
        {"id": "e1", "lineage_id": "e1", "type": "work", "name": "Кладка стен",
         "unit": "м3", "qty": 4, "price_work": price_work, "price_material": None,
         "price_list_name": "Прайс подрядчика №2"},
    ]


async def _signals(db_session, task_id: str) -> list[CorrectionSignal]:
    result = await db_session.execute(
        select(CorrectionSignal)
        .where(CorrectionSignal.task_id == task_id)
        .order_by(CorrectionSignal.created_at, CorrectionSignal.field)
    )
    return list(result.scalars().all())


@pytest_asyncio.fixture
async def env(db_session, fake_s3):
    """Проект → карточка → задачи «Перечень» и «Смета», у каждой рабочая версия."""
    for model in (CorrectionSignal, DocumentLock, EstimateVersion, TaskHistory,
                  WorkflowCard, Task, Project, User):
        await db_session.execute(model.__table__.delete())
    await db_session.commit()

    pm1 = User(username="pm1", role="project_manager", full_name="Иванов Иван",
               password_hash=hash_password("p1"))
    head = User(username="head", role="head_of_sales", full_name="Руководитель",
                password_hash=hash_password("p2"))
    db_session.add_all([pm1, head])
    await db_session.flush()

    project = Project(name="Объект АР", owner_id=pm1.id)
    db_session.add(project)
    await db_session.flush()

    list_task = Task(
        owner_id=pm1.id, user_role="project_manager", task_type="LIST_FROM_GRAND",
        status="completed", input_files=[], input_file_data=[], chat_history=[],
        project_id=str(project.id),
    )
    estimate_task = Task(
        owner_id=pm1.id, user_role="project_manager", task_type="ESTIMATE_FROM_LIST",
        status="completed", input_files=[], input_file_data=[], chat_history=[],
        project_id=str(project.id),
    )
    db_session.add_all([list_task, estimate_task])
    await db_session.flush()

    card = WorkflowCard(project_id=str(project.id), name="АР", stage="estimate",
                        list_task_id=str(list_task.id),
                        estimate_task_id=str(estimate_task.id))
    db_session.add(card)

    list_version = EstimateVersion(
        task_id=str(list_task.id), version_number=0, version_label="original",
        version_display_name="V0", rows=_list_rows(),
        file_slot="result", task_type="LIST_FROM_GRAND",
    )
    estimate_version = EstimateVersion(
        task_id=str(estimate_task.id), version_number=0, version_label="original",
        version_display_name="V0", rows=_estimate_rows(),
        # Слот сметы — «estimate», а не «result»: см. `_KIND_TO_FILE_SLOT`.
        file_slot="estimate", task_type="ESTIMATE_FROM_LIST",
    )
    db_session.add_all([list_version, estimate_version])
    await db_session.commit()

    yield {
        "pm1": pm1.id, "head": head.id, "card_id": str(card.id),
        "list_task_id": str(list_task.id), "list_version_id": str(list_version.id),
        "estimate_task_id": str(estimate_task.id),
        "estimate_version_id": str(estimate_version.id),
    }

    for model in (CorrectionSignal, DocumentLock, EstimateVersion, TaskHistory,
                  WorkflowCard, Task, Project, User):
        await db_session.execute(model.__table__.delete())
    await db_session.commit()


@pytest.mark.asyncio
async def test_manual_edit_writes_signal_with_machine_field_key(
    async_client, db_session, env
):
    """Правка цены в перечне → сигнал «3000 → 2500» с машинным ключом поля."""
    r = await async_client.post(
        f"/documents/{env['card_id']}/list/apply",
        json={"version_id": env["list_version_id"], "rev": 0, "rows": _list_rows(2500)},
        headers=_pm1(env),
    )
    assert r.status_code == 200, r.text

    signals = await _signals(db_session, env["list_task_id"])
    assert len(signals) == 1
    signal = signals[0]
    assert signal.document_kind == "list"
    assert signal.row_key == "r1"
    assert signal.row_name == "Разработка грунта"
    assert signal.row_type == "work"
    assert signal.unit == "м3"
    # Ключ поля — имя колонки исходного файла, а не подпись из истории.
    assert signal.field == "Цена работ"
    assert signal.previous_value == "3000"
    assert signal.new_value == "2500"
    assert float(signal.previous_num) == 3000.0
    assert float(signal.new_num) == 2500.0
    assert signal.is_first_touch is True
    assert signal.user_name == "Иванов Иван"


@pytest.mark.asyncio
async def test_estimate_edit_keeps_price_source(async_client, db_session, env):
    """У сметы в сигнал едет машинный ключ `price_work` и источник цены.

    Без источника непонятно, что чинить: прайс, кеш прошлых задач или ИИ-поиск.
    """
    r = await async_client.post(
        f"/documents/{env['card_id']}/estimate/apply",
        json={"version_id": env["estimate_version_id"], "rev": 0,
              "rows": _estimate_rows(2500.0)},
        headers=_pm1(env),
    )
    assert r.status_code == 200, r.text

    signals = await _signals(db_session, env["estimate_task_id"])
    price = [s for s in signals if s.field == "price_work"]
    assert len(price) == 1, [s.field for s in signals]
    assert price[0].row_type == "work"
    assert price[0].unit == "м3"
    assert price[0].price_source == "Прайс подрядчика №2"
    assert float(price[0].previous_num) == 3000.0
    assert float(price[0].new_num) == 2500.0


@pytest.mark.asyncio
async def test_second_edit_of_same_cell_is_not_first_touch(
    async_client, db_session, env
):
    """Правка правки — не ошибка системы: «было» тут уже человеческое число."""
    for rev, price in ((0, 2500), (1, 2400)):
        r = await async_client.post(
            f"/documents/{env['card_id']}/list/apply",
            json={"version_id": env["list_version_id"], "rev": rev,
                  "rows": _list_rows(price)},
            headers=_pm1(env),
        )
        assert r.status_code == 200, r.text

    signals = await _signals(db_session, env["list_task_id"])
    assert len(signals) == 2
    first, second = signals
    assert (first.previous_value, first.new_value) == ("3000", "2500")
    assert first.is_first_touch is True
    assert (second.previous_value, second.new_value) == ("2500", "2400")
    assert second.is_first_touch is False


@pytest.mark.asyncio
async def test_added_and_removed_rows_are_signals(async_client, db_session, env):
    """Пропущенная и лишняя позиция — самый ценный сигнал, поле `__row`."""
    rows = _list_rows()
    rows.pop()  # убрали «Песок»
    rows.append({
        "row_id": "r3",
        "cells": {"Тип": "Материал", "Наименование": "Щебень",
                  "Ед. изм": "т", "Кол-во": 5, "Цена работ": 900},
    })

    r = await async_client.post(
        f"/documents/{env['card_id']}/list/apply",
        json={"version_id": env["list_version_id"], "rev": 0, "rows": rows},
        headers=_pm1(env),
    )
    assert r.status_code == 200, r.text

    signals = await _signals(db_session, env["list_task_id"])
    by_row = {s.row_key: s for s in signals if s.field == FIELD_ROW}
    assert by_row["r3"].new_value == "добавлена"
    assert by_row["r3"].row_name == "Щебень"
    assert by_row["r2"].new_value == "удалена"
    assert by_row["r2"].row_name == "Песок"


@pytest.mark.asyncio
async def test_automatic_operations_are_not_signals(async_client, db_session, env):
    """Проверка цен правит смету через тот же `apply_rows` — но это не правка человека."""
    from app.services import document_service as svc

    doc = await svc.resolve_document(
        db_session, env["card_id"], "estimate",
        {"sub": str(env["pm1"]), "role": "project_manager", "username": "pm1"}, None,
    )
    version = svc.pick_version(doc, env["estimate_version_id"])
    await svc.apply_rows(
        db_session, doc, version, _estimate_rows(2500.0), 0,
        {"sub": str(env["pm1"]), "role": "project_manager", "username": "pm1"},
        operation_type="price_units_check",
    )

    assert await _signals(db_session, env["estimate_task_id"]) == []


@pytest.mark.asyncio
async def test_journal_failure_does_not_break_apply(
    async_client, db_session, env, monkeypatch
):
    """Правка документа важнее журнала: его сбой не имеет права её отменить."""
    from app.services import correction_log

    async def _boom(*args, **kwargs):
        raise RuntimeError("журнал упал")

    monkeypatch.setattr(correction_log, "_record", _boom)

    r = await async_client.post(
        f"/documents/{env['card_id']}/list/apply",
        json={"version_id": env["list_version_id"], "rev": 0, "rows": _list_rows(2500)},
        headers=_pm1(env),
    )
    assert r.status_code == 200, r.text

    rows_resp = await async_client.get(
        f"/documents/{env['card_id']}/list/rows", headers=_pm1(env))
    assert rows_resp.json()["rows"][0]["cells"]["Цена работ"] == 2500
    assert await _signals(db_session, env["list_task_id"]) == []


# ── Отчёт (Фаза 2) ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stats_counts_only_first_touch_as_system_error(
    async_client, db_session, env
):
    """Метрика качества считается по первым касаниям, лента — по всему."""
    for rev, price in ((0, 2500), (1, 2400)):
        r = await async_client.post(
            f"/documents/{env['card_id']}/list/apply",
            json={"version_id": env["list_version_id"], "rev": rev,
                  "rows": _list_rows(price)},
            headers=_pm1(env),
        )
        assert r.status_code == 200, r.text

    head = _auth(env["head"], "head_of_sales", "head")
    stats = await async_client.get("/corrections/stats", headers=head)
    assert stats.status_code == 200, stats.text
    body = stats.json()
    assert body["total"] == 2
    assert body["first_touch"] == 1
    assert body["price_edits"] == 1
    assert body["by_kind"] == [{"document_kind": "list", "count": 2}]
    assert body["top_fields"] == [
        {"field": "Цена работ", "document_kind": "list", "count": 1}
    ]
    assert body["top_positions"] == [
        {"row_name": "Разработка грунта", "document_kind": "list", "count": 1}
    ]

    feed = await async_client.get("/corrections", headers=head)
    assert [(c["previous_value"], c["new_value"]) for c in feed.json()] == [("3000", "2500")]

    full = await async_client.get(
        "/corrections", params={"first_touch_only": False}, headers=head)
    assert len(full.json()) == 2


@pytest.mark.asyncio
async def test_added_and_removed_rows_counted_separately(
    async_client, db_session, env
):
    """«Пропустили позицию» и «выдумали лишнюю» — отдельные цифры отчёта."""
    rows = _list_rows()
    rows.pop()
    rows.append({
        "row_id": "r3",
        "cells": {"Тип": "Материал", "Наименование": "Щебень",
                  "Ед. изм": "т", "Кол-во": 5, "Цена работ": 900},
    })
    r = await async_client.post(
        f"/documents/{env['card_id']}/list/apply",
        json={"version_id": env["list_version_id"], "rev": 0, "rows": rows},
        headers=_pm1(env),
    )
    assert r.status_code == 200, r.text

    stats = await async_client.get(
        "/corrections/stats", headers=_auth(env["head"], "head_of_sales", "head"))
    body = stats.json()
    assert body["rows_added"] == 1
    assert body["rows_removed"] == 1


@pytest.mark.asyncio
async def test_report_is_closed_for_project_manager(async_client, env):
    """Отчёт — управленческая метрика: рядовому менеджеру он закрыт."""
    for path in ("/corrections/stats", "/corrections"):
        r = await async_client.get(path, headers=_pm1(env))
        assert r.status_code == 403, (path, r.text)
