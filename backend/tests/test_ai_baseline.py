"""Снимок «что выдал ИИ»: пишется один раз и не перезаписывается никогда.

План: plans/2026-09-10-sverka-i-obuchenie-na-pravkah.md, Фаза 1.

Проверяется то, без чего снимок соврал бы:
- правка документа его не трогает (а версию V0 перечня — трогает, в этом и суть);
- повторный прогон задачи не подменяет снимок правлеными строками;
- задачу, которую уже правили руками, снимком не накрываем задним числом;
- строки снимка — копия, а не ссылка на живой список;
- слишком большой снимок усекается и честно об этом говорит.
"""
import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.ai_baseline import MAX_BASELINE_ROWS, AiBaseline
from app.models.document_lock import DocumentLock
from app.models.estimate_version import EstimateVersion
from app.models.history import TaskHistory
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.models.workflow_card import WorkflowCard
from app.services import ai_baseline
from app.utils.auth import create_access_token, hash_password

_MODELS = (AiBaseline, DocumentLock, EstimateVersion, TaskHistory,
           WorkflowCard, Task, Project, User)


def _auth(user_id: int, role: str, username: str) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id, role, username)}"}


def _list_rows(price_work: int = 3000) -> list[dict]:
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
async def env(db_session, fake_s3):
    for model in _MODELS:
        await db_session.execute(model.__table__.delete())
    await db_session.commit()

    pm1 = User(username="pm1", role="project_manager", full_name="Иванов Иван",
               password_hash=hash_password("p1"))
    db_session.add(pm1)
    await db_session.flush()

    project = Project(name="Объект АР", owner_id=pm1.id)
    db_session.add(project)
    await db_session.flush()

    list_task = Task(
        owner_id=pm1.id, user_role="project_manager", task_type="LIST_FROM_GRAND",
        status="completed", input_files=[], input_file_data=[], chat_history=[],
        project_id=str(project.id),
    )
    db_session.add(list_task)
    await db_session.flush()

    card = WorkflowCard(project_id=str(project.id), name="АР", stage="list",
                        list_task_id=str(list_task.id))
    db_session.add(card)

    version = EstimateVersion(
        task_id=str(list_task.id), version_number=0, version_label="original",
        version_display_name="V0", rows=_list_rows(),
        file_slot="result", task_type="LIST_FROM_GRAND",
    )
    db_session.add(version)
    await db_session.commit()

    yield {
        "pm1": pm1.id, "card_id": str(card.id),
        "task_id": str(list_task.id), "version_id": str(version.id),
    }

    for model in _MODELS:
        await db_session.execute(model.__table__.delete())
    await db_session.commit()


async def _baseline(db_session, task_id: str, kind: str = "list"):
    db_session.expire_all()
    result = await db_session.execute(
        select(AiBaseline).where(
            AiBaseline.task_id == task_id, AiBaseline.document_kind == kind
        )
    )
    return result.scalar_one_or_none()


@pytest.mark.asyncio
async def test_snapshot_saved_once(db_session, env):
    """Первый вызов пишет снимок, второй — нет, и снимок остаётся прежним."""
    first = await ai_baseline.save_once(
        db_session, task_id=env["task_id"], document_kind="list", rows=_list_rows(3000)
    )
    second = await ai_baseline.save_once(
        db_session, task_id=env["task_id"], document_kind="list", rows=_list_rows(2500)
    )

    assert first is True
    assert second is False

    saved = await _baseline(db_session, env["task_id"])
    assert saved.row_count == 2
    assert saved.truncated is False
    assert saved.rows[0]["cells"]["Цена работ"] == 3000


@pytest.mark.asyncio
async def test_snapshot_is_a_copy_not_a_reference(db_session, env):
    """Строки после записи живут своей жизнью — снимок это не должно трогать."""
    rows = _list_rows(3000)
    await ai_baseline.save_once(
        db_session, task_id=env["task_id"], document_kind="list", rows=rows
    )

    rows[0]["cells"]["Цена работ"] = 999  # документ поехал дальше

    saved = await _baseline(db_session, env["task_id"])
    assert saved.rows[0]["cells"]["Цена работ"] == 3000


@pytest.mark.asyncio
async def test_manual_edit_does_not_touch_snapshot(async_client, db_session, env):
    """«Применить» переписывает версию V0 перечня, но не снимок."""
    await ai_baseline.save_once(
        db_session, task_id=env["task_id"], document_kind="list", rows=_list_rows(3000)
    )

    edited = _list_rows(3000)
    edited[0]["cells"]["Цена работ"] = 2500
    r = await async_client.post(
        f"/documents/{env['card_id']}/list/apply",
        json={"version_id": env["version_id"], "rev": 0, "rows": edited},
        headers=_auth(env["pm1"], "project_manager", "pm1"),
    )
    assert r.status_code == 200

    db_session.expire_all()
    version = await db_session.get(EstimateVersion, env["version_id"])
    assert version.rows[0]["cells"]["Цена работ"] == 2500  # документ поехал

    saved = await _baseline(db_session, env["task_id"])
    assert saved.rows[0]["cells"]["Цена работ"] == 3000  # снимок остался


@pytest.mark.asyncio
async def test_edited_task_gets_no_snapshot(db_session, env):
    """Задачу, которую уже правили руками, снимком задним числом не накрываем."""
    from datetime import datetime, timezone

    written = await ai_baseline.save_once(
        db_session,
        task_id=env["task_id"],
        document_kind="list",
        rows=_list_rows(2500),
        edited_at=datetime.now(timezone.utc),
    )

    assert written is False
    assert await _baseline(db_session, env["task_id"]) is None


@pytest.mark.asyncio
async def test_empty_rows_do_not_occupy_the_slot(db_session, env):
    """Пустой расчёт снимком не является и не закрывает дорогу настоящему."""
    assert await ai_baseline.save_once(
        db_session, task_id=env["task_id"], document_kind="list", rows=[]
    ) is False

    assert await ai_baseline.save_once(
        db_session, task_id=env["task_id"], document_kind="list", rows=_list_rows()
    ) is True


@pytest.mark.asyncio
async def test_optimization_kind_has_no_baseline(db_session, env):
    """Оптимизация — работа над готовой сметой, первичного вывода ИИ там нет."""
    written = await ai_baseline.save_once(
        db_session, task_id=env["task_id"], document_kind="optimization",
        rows=_list_rows(),
    )

    assert written is False
    assert await _baseline(db_session, env["task_id"], "optimization") is None


@pytest.mark.asyncio
async def test_huge_snapshot_is_truncated_and_says_so(db_session, env):
    """Сверх потолка снимок пишется усечённым, но число строк — настоящее."""
    rows = [
        {"row_id": f"r{i}", "cells": {"Наименование": f"Позиция {i}", "Кол-во": i}}
        for i in range(MAX_BASELINE_ROWS + 7)
    ]

    await ai_baseline.save_once(
        db_session, task_id=env["task_id"], document_kind="list", rows=rows
    )

    saved = await _baseline(db_session, env["task_id"])
    assert saved.truncated is True
    assert saved.row_count == MAX_BASELINE_ROWS + 7
    assert len(saved.rows) == MAX_BASELINE_ROWS


@pytest.mark.asyncio
async def test_read_returns_none_for_task_without_snapshot(db_session, env):
    """Задача, посчитанная до появления снимков, ничего не ломает."""
    assert await ai_baseline.read(
        db_session, task_id=env["task_id"], document_kind="list"
    ) is None
