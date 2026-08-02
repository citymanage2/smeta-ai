"""Единый документный API: черновик, применение, история, права, блокировка.

Фаза 1 плана `plans/2026-08-02-edinyy-redaktor-tablic.md`.

Документ = (карточка сметы, тип документа). Один и тот же контракт для всех
типов; здесь проверяется поведение оболочки: черновик → «Применить» → история,
защита от перезаписи чужих правок (rev), права на запись, блокировка на время
расчёта, неприкосновенность входного файла заказчика и присутствие.
"""
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.document_lock import DocumentLock
from app.models.estimate_version import EstimateVersion
from app.models.history import TaskHistory
from app.models.project import Project
from app.models.task import Task
from app.models.task_input_file import TaskInputFile
from app.models.user import User
from app.models.workflow_card import WorkflowCard
from app.services import storage_service
from app.utils.auth import create_access_token, hash_password


def _auth(user_id: int, role: str, username: str = None) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id, role, username)}"}


def _rows(price_work: int = 3000) -> list[dict]:
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


@pytest_asyncio.fixture
async def doc_env(db_session, fake_s3):
    """Проект pm1 → карточка → задача «Перечень» → версия V0 + входной файл."""
    # DocumentLock чистим явно: в SQLite внешние ключи выключены, каскад от
    # workflow_cards не срабатывает и записи присутствия текут между тестами.
    for model in (DocumentLock, EstimateVersion, TaskHistory, WorkflowCard,
                  TaskInputFile, Task, Project, User):
        await db_session.execute(model.__table__.delete())
    await db_session.commit()

    pm1 = User(username="pm1", role="project_manager", full_name="Иванов Иван",
               password_hash=hash_password("p1"))
    pm2 = User(username="pm2", role="project_manager", full_name="Петров Пётр",
               password_hash=hash_password("p2"))
    head = User(username="head", role="head_of_sales", full_name="Руководитель",
                password_hash=hash_password("p3"))
    db_session.add_all([pm1, pm2, head])
    await db_session.flush()

    project = Project(name="Объект АР", owner_id=pm1.id)
    db_session.add(project)
    await db_session.flush()

    task = Task(
        owner_id=pm1.id, user_role="project_manager", task_type="LIST_FROM_GRAND",
        status="completed", input_files=[], input_file_data=[], chat_history=[],
        project_id=str(project.id),
    )
    db_session.add(task)
    await db_session.flush()

    # Входной файл заказчика — байты в fake-S3, их никто не должен переписывать
    input_key = storage_service.build_input_key(str(task.id), 0, "original.xlsx")
    await storage_service.put_object(input_key, b"ORIGINAL-CUSTOMER-BYTES",
                                     "application/vnd.ms-excel")
    db_session.add(TaskInputFile(
        task_id=str(task.id), file_index=0, file_name="original.xlsx",
        mime_type="application/vnd.ms-excel", size_bytes=23, storage_key=input_key,
    ))

    card = WorkflowCard(project_id=str(project.id), name="АР", stage="list",
                        list_task_id=str(task.id))
    db_session.add(card)

    version = EstimateVersion(
        task_id=str(task.id), version_number=0, version_label="original",
        version_display_name="V0 — Оригинал", rows=_rows(),
        file_slot="result", task_type="LIST_FROM_GRAND",
    )
    input_version = EstimateVersion(
        task_id=str(task.id), version_number=1, version_label="input_0",
        version_display_name="V0 — Оригинал (файл 0)", rows=_rows(),
        file_slot="input", task_type="LIST_FROM_GRAND",
    )
    db_session.add_all([version, input_version])
    await db_session.commit()

    env = {
        "pm1": pm1.id, "pm2": pm2.id, "head": head.id,
        "project_id": str(project.id), "card_id": str(card.id),
        "task_id": str(task.id), "version_id": str(version.id),
        "input_version_id": str(input_version.id), "input_key": input_key,
    }
    yield env

    # DocumentLock чистим явно: в SQLite внешние ключи выключены, каскад от
    # workflow_cards не срабатывает и записи присутствия текут между тестами.
    for model in (DocumentLock, EstimateVersion, TaskHistory, WorkflowCard,
                  TaskInputFile, Task, Project, User):
        await db_session.execute(model.__table__.delete())
    await db_session.commit()


def _pm1(env):
    return _auth(env["pm1"], "project_manager", "pm1")


# ---------------------------------------------------------------------------
# Метаданные документа
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_meta_returns_kind_format_and_versions(async_client, doc_env):
    r = await async_client.get(
        f"/documents/{doc_env['card_id']}/list", headers=_pm1(doc_env))
    assert r.status_code == 200
    meta = r.json()
    assert meta["kind"] == "list"
    assert meta["row_format"] == "generic"
    assert meta["can_write"] is True
    assert meta["readonly_reason"] is None
    assert meta["rev"] == 0
    assert meta["active_version_id"] == doc_env["version_id"]
    assert any(v["id"] == doc_env["version_id"] for v in meta["versions"])


@pytest.mark.asyncio
async def test_project_percentages_default_to_3(async_client, doc_env):
    r = await async_client.get(
        f"/documents/{doc_env['card_id']}/list", headers=_pm1(doc_env))
    assert r.status_code == 200
    assert float(r.json()["project"]["overhead_pct"]) == 3.0
    assert float(r.json()["project"]["transport_pct"]) == 3.0


@pytest.mark.asyncio
async def test_unknown_kind_returns_404(async_client, doc_env):
    r = await async_client.get(
        f"/documents/{doc_env['card_id']}/nonsense", headers=_pm1(doc_env))
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Черновик → Применить → История
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_draft_is_saved_without_touching_rows(async_client, doc_env, db_session):
    edited = _rows(price_work=2500)
    r = await async_client.put(
        f"/documents/{doc_env['card_id']}/list/draft",
        json={"version_id": doc_env["version_id"], "rows": edited},
        headers=_pm1(doc_env),
    )
    assert r.status_code == 200

    rows_resp = await async_client.get(
        f"/documents/{doc_env['card_id']}/list/rows", headers=_pm1(doc_env))
    body = rows_resp.json()
    # Рабочие строки не изменились, черновик отдаётся отдельно
    assert body["rows"][0]["cells"]["Цена работ"] == 3000
    assert body["draft_rows"][0]["cells"]["Цена работ"] == 2500

    meta = await async_client.get(
        f"/documents/{doc_env['card_id']}/list", headers=_pm1(doc_env))
    assert meta.json()["has_draft"] is True


@pytest.mark.asyncio
async def test_draft_then_apply_creates_history_entry(async_client, doc_env, db_session):
    edited = _rows(price_work=2500)
    await async_client.put(
        f"/documents/{doc_env['card_id']}/list/draft",
        json={"version_id": doc_env["version_id"], "rows": edited},
        headers=_pm1(doc_env),
    )
    r = await async_client.post(
        f"/documents/{doc_env['card_id']}/list/apply",
        json={"version_id": doc_env["version_id"], "rev": 0},
        headers=_pm1(doc_env),
    )
    assert r.status_code == 200
    assert r.json()["rev"] == 1

    rows_resp = await async_client.get(
        f"/documents/{doc_env['card_id']}/list/rows", headers=_pm1(doc_env))
    assert rows_resp.json()["rows"][0]["cells"]["Цена работ"] == 2500
    assert rows_resp.json()["draft_rows"] is None

    hist = await async_client.get(
        f"/documents/{doc_env['card_id']}/list/history", headers=_pm1(doc_env))
    entries = hist.json()
    assert len(entries) == 1
    entry = entries[0]
    assert entry["user_name"] == "Иванов Иван"
    assert entry["changes_count"] == 1
    change = entry["changes"][0]
    assert change["row_number"] == 1
    assert change["field"] == "Цена работ"
    assert str(change["previous"]) == "3000"
    assert str(change["new"]) == "2500"


@pytest.mark.asyncio
async def test_apply_without_draft_uses_body_rows(async_client, doc_env):
    r = await async_client.post(
        f"/documents/{doc_env['card_id']}/list/apply",
        json={"version_id": doc_env["version_id"], "rev": 0, "rows": _rows(1111)},
        headers=_pm1(doc_env),
    )
    assert r.status_code == 200
    rows_resp = await async_client.get(
        f"/documents/{doc_env['card_id']}/list/rows", headers=_pm1(doc_env))
    assert rows_resp.json()["rows"][0]["cells"]["Цена работ"] == 1111


@pytest.mark.asyncio
async def test_apply_with_stale_rev_returns_409(async_client, doc_env):
    first = await async_client.post(
        f"/documents/{doc_env['card_id']}/list/apply",
        json={"version_id": doc_env["version_id"], "rev": 0, "rows": _rows(2500)},
        headers=_pm1(doc_env),
    )
    assert first.status_code == 200

    stale = await async_client.post(
        f"/documents/{doc_env['card_id']}/list/apply",
        json={"version_id": doc_env["version_id"], "rev": 0, "rows": _rows(2000)},
        headers=_auth(doc_env["head"], "head_of_sales", "head"),
    )
    assert stale.status_code == 409
    assert "Иванов Иван" in stale.json()["detail"]

    # Данные первого сохранения не затёрты
    rows_resp = await async_client.get(
        f"/documents/{doc_env['card_id']}/list/rows", headers=_pm1(doc_env))
    assert rows_resp.json()["rows"][0]["cells"]["Цена работ"] == 2500


@pytest.mark.asyncio
async def test_apply_guard_is_atomic_not_just_a_precheck(async_client, doc_env, db_session):
    """Гонка: rev в БД уже уехал, а объект в памяти этого ещё не знает.

    Быстрая проверка `client_rev != version.rev` такое пропустит — от тихого
    затирания защищает условный UPDATE ... WHERE rev = client_rev.
    """
    from sqlalchemy import update as sa_update

    from app.services import document_service as svc

    user = {"sub": str(doc_env["pm1"]), "role": "project_manager"}
    doc = await svc.resolve_document(db_session, doc_env["card_id"], "list", user)
    version = svc.pick_version(doc, None)
    version_id = version.id  # после отката ORM-объект сброшен, id берём заранее
    assert version.rev == 0  # объект в памяти

    # Кто-то другой успел сохранить: правим строку мимо ORM-объекта.
    await db_session.execute(
        sa_update(EstimateVersion)
        .where(EstimateVersion.id == version_id)
        .values(rev=7)
        .execution_options(synchronize_session=False)
    )
    await db_session.commit()

    with pytest.raises(Exception) as exc:
        await svc.apply_rows(db_session, doc, version, _rows(4242), 0, user)
    assert getattr(exc.value, "status_code", None) == 409

    fresh = await db_session.get(EstimateVersion, version_id)
    await db_session.refresh(fresh)
    assert fresh.rev == 7
    assert fresh.rows[0]["cells"]["Цена работ"] == 3000  # ничего не затёрто


@pytest.mark.asyncio
async def test_legacy_save_bumps_rev_so_new_editor_cannot_overwrite(
    async_client, doc_env
):
    """Переходный период: старый редактор пишет в те же строки.

    Его сохранение обязано двигать rev, иначе открытый рядом новый редактор
    затёр бы эти правки, не заметив их.
    """
    legacy = await async_client.put(
        f"/tasks/{doc_env['task_id']}/estimate/versions/{doc_env['version_id']}/rows",
        json={"rows": _rows(1500)}, headers=_pm1(doc_env))
    assert legacy.status_code == 200

    stale = await async_client.post(
        f"/documents/{doc_env['card_id']}/list/apply",
        json={"version_id": doc_env["version_id"], "rev": 0, "rows": _rows(9)},
        headers=_pm1(doc_env))
    assert stale.status_code == 409

    rows_resp = await async_client.get(
        f"/documents/{doc_env['card_id']}/list/rows", headers=_pm1(doc_env))
    assert rows_resp.json()["rows"][0]["cells"]["Цена работ"] == 1500


@pytest.mark.asyncio
async def test_apply_without_changes_writes_no_history(async_client, doc_env):
    r = await async_client.post(
        f"/documents/{doc_env['card_id']}/list/apply",
        json={"version_id": doc_env["version_id"], "rev": 0, "rows": _rows()},
        headers=_pm1(doc_env),
    )
    assert r.status_code == 200
    hist = await async_client.get(
        f"/documents/{doc_env['card_id']}/list/history", headers=_pm1(doc_env))
    assert hist.json() == []


@pytest.mark.asyncio
async def test_history_is_trimmed_and_old_snapshots_dropped(async_client, doc_env, db_session):
    """История не растёт без предела: снимки строк — только у последних записей.

    Снимок «как было» весит столько же, сколько сам документ; без ограничения
    документ на 2000 строк раздул бы БД на десятки мегабайт за месяц работы.
    """
    from app.services.document_service import HISTORY_DEPTH, SNAPSHOT_DEPTH
    from app.services import document_service as svc

    user = {"sub": str(doc_env["pm1"]), "role": "project_manager"}
    doc = await svc.resolve_document(db_session, doc_env["card_id"], "list", user)
    version = svc.pick_version(doc, None)

    total_applies = HISTORY_DEPTH + 5
    for i in range(total_applies):
        doc = await svc.resolve_document(db_session, doc_env["card_id"], "list", user)
        version = svc.pick_version(doc, None)
        await svc.apply_rows(db_session, doc, version, _rows(1000 + i), version.rev, user)

    entries = await svc.list_history(db_session, doc)
    assert len(entries) == HISTORY_DEPTH

    rows_snapshots = (await db_session.execute(
        select(TaskHistory)
        .where(TaskHistory.task_id == doc_env["task_id"])
        .order_by(TaskHistory.created_at.desc())
    )).scalars().all()
    with_snapshot = [
        e for e in rows_snapshots
        if isinstance(e.previous_value, dict) and e.previous_value.get("rows") is not None
    ]
    assert len(with_snapshot) == SNAPSHOT_DEPTH

    # Свежая запись всё ещё позволяет откатиться
    latest_id = str(rows_snapshots[0].id)
    r = await async_client.post(
        f"/documents/{doc_env['card_id']}/list/history/{latest_id}/revert",
        headers=_pm1(doc_env))
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Откат
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_revert_restores_previous_rows(async_client, doc_env):
    await async_client.post(
        f"/documents/{doc_env['card_id']}/list/apply",
        json={"version_id": doc_env["version_id"], "rev": 0, "rows": _rows(2500)},
        headers=_pm1(doc_env),
    )
    hist = await async_client.get(
        f"/documents/{doc_env['card_id']}/list/history", headers=_pm1(doc_env))
    entry_id = hist.json()[0]["id"]

    r = await async_client.post(
        f"/documents/{doc_env['card_id']}/list/history/{entry_id}/revert",
        headers=_pm1(doc_env),
    )
    assert r.status_code == 200

    rows_resp = await async_client.get(
        f"/documents/{doc_env['card_id']}/list/rows", headers=_pm1(doc_env))
    assert rows_resp.json()["rows"][0]["cells"]["Цена работ"] == 3000
    assert rows_resp.json()["rev"] == 2  # откат — тоже изменение


# ---------------------------------------------------------------------------
# Права
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pm_cannot_write_foreign_document(async_client, doc_env):
    """Менеджер проектов правит только свои документы (чужое — как несуществующее)."""
    hdr = _auth(doc_env["pm2"], "project_manager", "pm2")
    draft = await async_client.put(
        f"/documents/{doc_env['card_id']}/list/draft",
        json={"version_id": doc_env["version_id"], "rows": _rows(1)}, headers=hdr)
    assert draft.status_code == 404

    apply = await async_client.post(
        f"/documents/{doc_env['card_id']}/list/apply",
        json={"version_id": doc_env["version_id"], "rev": 0, "rows": _rows(1)},
        headers=hdr)
    assert apply.status_code == 404


@pytest.mark.asyncio
async def test_head_of_sales_can_write_foreign_document(async_client, doc_env):
    hdr = _auth(doc_env["head"], "head_of_sales", "head")
    r = await async_client.post(
        f"/documents/{doc_env['card_id']}/list/apply",
        json={"version_id": doc_env["version_id"], "rev": 0, "rows": _rows(1234)},
        headers=hdr)
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_readonly_query_param_cannot_grant_write(async_client, doc_env):
    """Режим доступа определяется сервером, а не параметром в адресе."""
    hdr = _auth(doc_env["pm2"], "project_manager", "pm2")
    r = await async_client.post(
        f"/documents/{doc_env['card_id']}/list/apply?read_only=0",
        json={"version_id": doc_env["version_id"], "rev": 0, "rows": _rows(1)},
        headers=hdr)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Блокировка на время расчёта
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("status_value", ["processing", "pending"])
async def test_write_blocked_while_task_processing(
    async_client, doc_env, db_session, status_value
):
    task = await db_session.get(Task, doc_env["task_id"])
    task.status = status_value
    await db_session.commit()

    meta = await async_client.get(
        f"/documents/{doc_env['card_id']}/list", headers=_pm1(doc_env))
    assert meta.json()["can_write"] is False
    assert meta.json()["readonly_reason"] == "task_processing"

    r = await async_client.post(
        f"/documents/{doc_env['card_id']}/list/apply",
        json={"version_id": doc_env["version_id"], "rev": 0, "rows": _rows(1)},
        headers=_pm1(doc_env))
    assert r.status_code == 409
    assert "расч" in r.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Входной файл заказчика неприкосновенен
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_input_document_is_read_only(async_client, doc_env, fake_s3):
    """Документ входного файла отдаётся только на чтение и не пересобирается."""
    meta = await async_client.get(
        f"/documents/{doc_env['card_id']}/list?file_slot=input", headers=_pm1(doc_env))
    assert meta.status_code == 200
    assert meta.json()["can_write"] is False
    assert meta.json()["readonly_reason"] == "input_readonly"

    r = await async_client.post(
        f"/documents/{doc_env['card_id']}/list/apply?file_slot=input",
        json={"version_id": doc_env["input_version_id"], "rev": 0, "rows": _rows(7)},
        headers=_pm1(doc_env))
    assert r.status_code == 409
    assert fake_s3.store[doc_env["input_key"]] == b"ORIGINAL-CUSTOMER-BYTES"


@pytest.mark.asyncio
async def test_legacy_endpoint_never_overwrites_input_file(
    async_client, doc_env, fake_s3
):
    """Старый эндпоинт сохранения строк тоже не трогает файл заказчика."""
    r = await async_client.put(
        f"/tasks/{doc_env['task_id']}/estimate/versions/{doc_env['input_version_id']}/rows",
        json={"rows": _rows(7)}, headers=_pm1(doc_env))
    assert r.status_code == 200
    assert fake_s3.store[doc_env["input_key"]] == b"ORIGINAL-CUSTOMER-BYTES"


# ---------------------------------------------------------------------------
# Первое открытие: версия создаётся из файла
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def fresh_card(db_session, doc_env, fake_s3):
    """Карточка с готовой задачей, но без единой версии — как сразу после расчёта."""
    from app.models.result import TaskResult
    from app.utils.xlsx_generic import rows_to_xlsx

    task = Task(
        owner_id=doc_env["pm1"], user_role="project_manager",
        task_type="LIST_FROM_GRAND", status="completed",
        input_files=[], input_file_data=[], chat_history=[],
        project_id=doc_env["project_id"],
    )
    db_session.add(task)
    await db_session.flush()

    xlsx = rows_to_xlsx([
        {"row_id": "a", "cells": {"Наименование": "Кладка", "Кол-во": 12}},
        {"row_id": "b", "cells": {"Наименование": "Штукатурка", "Кол-во": 30}},
    ])
    key = storage_service.build_result_key(str(task.id), "result", "perechen.xlsx")
    await storage_service.put_object(key, xlsx, "application/vnd.ms-excel")
    db_session.add(TaskResult(
        task_id=str(task.id), file_name="perechen.xlsx",
        mime_type="application/vnd.ms-excel", storage_key=key,
        size_bytes=len(xlsx), slot="result",
    ))

    card = WorkflowCard(
        project_id=doc_env["project_id"], name="Фасад", stage="list",
        list_task_id=str(task.id),
    )
    db_session.add(card)
    await db_session.commit()
    return {"card_id": str(card.id), "task_id": str(task.id)}


@pytest.mark.asyncio
async def test_first_open_creates_version_from_result(async_client, doc_env, fresh_card):
    """Раньше версию заводил клиент при открытии; теперь — сервер, для всех точек входа."""
    meta = await async_client.get(
        f"/documents/{fresh_card['card_id']}/list", headers=_pm1(doc_env))
    assert meta.status_code == 200
    assert meta.json()["active_version_id"] is not None
    assert meta.json()["rev"] == 0

    rows = await async_client.get(
        f"/documents/{fresh_card['card_id']}/list/rows", headers=_pm1(doc_env))
    names = [r["cells"]["Наименование"] for r in rows.json()["rows"]]
    assert names == ["Кладка", "Штукатурка"]


@pytest.mark.asyncio
async def test_first_open_is_idempotent(async_client, doc_env, fresh_card, db_session):
    for _ in range(3):
        await async_client.get(
            f"/documents/{fresh_card['card_id']}/list", headers=_pm1(doc_env))

    versions = (await db_session.execute(
        select(EstimateVersion).where(EstimateVersion.task_id == fresh_card["task_id"])
    )).scalars().all()
    assert len(versions) == 1


@pytest.mark.asyncio
async def test_unfinished_task_does_not_create_version(
    async_client, doc_env, fresh_card, db_session
):
    task = await db_session.get(Task, fresh_card["task_id"])
    task.status = "processing"
    await db_session.commit()

    meta = await async_client.get(
        f"/documents/{fresh_card['card_id']}/list", headers=_pm1(doc_env))
    assert meta.json()["active_version_id"] is None
    assert meta.json()["can_write"] is False


@pytest.mark.asyncio
async def test_input_file_index_picks_the_right_document(async_client, doc_env, db_session):
    """У задачи может быть несколько исходных файлов — открывается запрошенный."""
    second = EstimateVersion(
        task_id=doc_env["task_id"], version_number=2, version_label="input_1",
        version_display_name="V0 — Оригинал (файл 1)",
        rows=[{"row_id": "x", "cells": {"Наименование": "Второй файл"}}],
        file_slot="input", task_type="LIST_FROM_GRAND",
    )
    db_session.add(second)
    await db_session.commit()

    rows = await async_client.get(
        f"/documents/{doc_env['card_id']}/list/rows?file_slot=input&file_index=1",
        headers=_pm1(doc_env))
    assert rows.json()["rows"][0]["cells"]["Наименование"] == "Второй файл"


# ---------------------------------------------------------------------------
# Поиск документа по задаче (для старых ссылок)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_locate_by_task_returns_card_and_kind(async_client, doc_env):
    r = await async_client.get(
        f"/documents/by-task/{doc_env['task_id']}", headers=_pm1(doc_env))
    assert r.status_code == 200
    assert r.json() == {
        "project_id": doc_env["project_id"],
        "card_id": doc_env["card_id"],
        "kind": "list",
    }


@pytest.mark.asyncio
async def test_locate_by_task_404_for_task_without_card(
    async_client, doc_env, db_session
):
    """Задача вне сметы карточки не имеет — старая страница задачи остаётся рабочей."""
    orphan = Task(
        owner_id=doc_env["pm1"], user_role="project_manager",
        task_type="LIST_FROM_GRAND", status="completed",
        input_files=[], input_file_data=[], chat_history=[],
    )
    db_session.add(orphan)
    await db_session.commit()

    r = await async_client.get(
        f"/documents/by-task/{orphan.id}", headers=_pm1(doc_env))
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_locate_by_task_denies_foreign_task(async_client, doc_env):
    r = await async_client.get(
        f"/documents/by-task/{doc_env['task_id']}",
        headers=_auth(doc_env["pm2"], "project_manager", "pm2"))
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Присутствие («Иван сейчас редактирует»)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_heartbeat_reports_other_editor(async_client, doc_env):
    """Вторым редактором может быть только тот, кто документ видит — здесь руководитель."""
    head_hdr = _auth(doc_env["head"], "head_of_sales", "head")

    first = await async_client.post(
        f"/documents/{doc_env['card_id']}/list/heartbeat", headers=_pm1(doc_env))
    assert first.status_code == 200
    assert first.json()["lock"] is None  # сам себя редактором не считаешь

    second = await async_client.post(
        f"/documents/{doc_env['card_id']}/list/heartbeat", headers=head_hdr)
    assert second.json()["lock"]["user_name"] == "Иванов Иван"

    meta = await async_client.get(
        f"/documents/{doc_env['card_id']}/list", headers=head_hdr)
    assert meta.json()["lock"]["user_name"] == "Иванов Иван"


@pytest.mark.asyncio
async def test_heartbeat_denied_for_foreign_document(async_client, doc_env):
    """Чужой документ не отдаёт даже присутствие — он для пользователя не существует."""
    r = await async_client.post(
        f"/documents/{doc_env['card_id']}/list/heartbeat",
        headers=_auth(doc_env["pm2"], "project_manager", "pm2"))
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_lock_expires_after_90s(async_client, doc_env, db_session):
    await async_client.post(
        f"/documents/{doc_env['card_id']}/list/heartbeat", headers=_pm1(doc_env))

    lock = (await db_session.execute(
        select(DocumentLock).where(DocumentLock.card_id == doc_env["card_id"])
    )).scalars().one()
    lock.heartbeat_at = datetime.now(timezone.utc) - timedelta(seconds=91)
    await db_session.commit()

    r = await async_client.post(
        f"/documents/{doc_env['card_id']}/list/heartbeat",
        headers=_auth(doc_env["head"], "head_of_sales", "head"))
    assert r.json()["lock"] is None  # протухшая запись не считается


@pytest.mark.asyncio
async def test_lock_does_not_block_saving(async_client, doc_env):
    """Присутствие — предупреждение, а не запрет: защищает только rev."""
    await async_client.post(
        f"/documents/{doc_env['card_id']}/list/heartbeat", headers=_pm1(doc_env))
    r = await async_client.post(
        f"/documents/{doc_env['card_id']}/list/apply",
        json={"version_id": doc_env["version_id"], "rev": 0, "rows": _rows(999)},
        headers=_auth(doc_env["head"], "head_of_sales", "head"))
    assert r.status_code == 200
