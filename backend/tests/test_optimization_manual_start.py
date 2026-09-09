"""Этап «Оптимизация» не запускается сам — только кнопкой «Начать оптимизацию».

План: `plans/2026-09-09-zapusk-optimizacii-knopkoj.md`.

До этой правки прикрепление сметы к этапу и её обработка были одним действием:
`start-task` в той же транзакции ставил job, worker забирал её, и этап
показывал «Идёт», хотя команды никто не давал. Здесь закреплено разделение:
прикрепили (`not_started`, job нет) → нажали (`pending`, ровно одна job).
"""
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.models.job import Job
from app.models.project import Project
from app.models.result import TaskResult  # noqa: F401  (регистрирует таблицу)
from app.models.task import Task
from app.models.user import User
from app.models.workflow_card import WorkflowCard
from app.utils.auth import create_access_token, hash_password
from tests.conftest import store_result_row

pytestmark = pytest.mark.asyncio

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _auth(user_id: int, role: str = "project_manager") -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id, role)}"}


@pytest_asyncio.fixture
async def owner(db_session) -> User:
    user = User(
        username=f"manual-start-{uuid.uuid4().hex[:8]}",
        full_name="Запускалкин З.З.",
        password_hash=hash_password("secret"),
        role="project_manager",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def project(db_session, owner) -> Project:
    proj = Project(name="Ручной запуск", owner_id=owner.id)
    db_session.add(proj)
    await db_session.commit()
    await db_session.refresh(proj)
    return proj


@pytest_asyncio.fixture
async def card(db_session, project, owner) -> WorkflowCard:
    """Смета с готовой стадией «Смета»: из неё и берётся файл для оптимизации."""
    await db_session.execute(delete(Job))
    task = Task(
        user_role="project_manager",
        owner_id=owner.id,
        task_type="ESTIMATE_FROM_LIST",
        status="completed",
        estimation_status="estimated",
        input_files=[],
        input_file_data=[],
        chat_history=[],
        progress_log=[],
        project_id=project.id,
    )
    db_session.add(task)
    await db_session.flush()
    await store_result_row(
        db_session, task.id, "estimate", "Смета.xlsx", XLSX_MIME, b"xlsx-bytes"
    )
    row = WorkflowCard(
        project_id=project.id, name="АР", stage="estimate", estimate_task_id=task.id
    )
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row


# id берём значениями ДО первого запроса: роутер зовёт `expire_all()` на той
# же сессии (в тестах она общая с приложением), после чего обращение к
# `card.id` полезло бы в БД из синхронного кода — MissingGreenlet.
async def _start(async_client, card_id: str, user_id: int):
    return await async_client.post(
        f"/api/workflow-cards/{card_id}/start-task",
        data={"task_type": "ESTIMATE_OPTIMIZATION", "use_previous_stage": "true"},
        headers=_auth(user_id),
    )


async def _launch(async_client, card_id: str, user_id: int):
    return await async_client.post(
        f"/api/workflow-cards/{card_id}/launch-task",
        data={"task_type": "ESTIMATE_OPTIMIZATION"},
        headers=_auth(user_id),
    )


async def _jobs_for(db_session, task_id: str) -> list[Job]:
    db_session.expire_all()
    jobs = (await db_session.execute(select(Job).where(Job.kind == "task.process"))).scalars().all()
    return [j for j in jobs if j.payload.get("task_id") == task_id]


async def test_attach_does_not_enqueue(async_client, db_session, project, card, owner):
    """Смета закрепилась за этапом, но в очередь не ушла."""
    resp = await _start(async_client, str(card.id), owner.id)
    assert resp.status_code == 200

    opt = resp.json()["optimization_task"]
    assert opt is not None, "смета должна быть закреплена за этапом"
    assert opt["status"] == "not_started"
    assert opt["input_files"], "файл сметы прикреплён к задаче"
    assert await _jobs_for(db_session, opt["id"]) == []


async def test_not_started_stage_has_no_queue_wait(
    async_client, db_session, project, card, owner
):
    """У незапущенной задачи не тикает ожидание в очереди и нет прогноза."""
    opt = (await _start(async_client, str(card.id), owner.id)).json()["optimization_task"]

    assert opt["usage"]["queue_seconds"] is None
    assert opt["usage"]["queue_running"] is False
    assert opt["eta"] is None


async def test_launch_starts_exactly_once(async_client, db_session, project, card, owner):
    """Кнопка ставит задачу в очередь; второе нажатие второй job не создаёт."""
    card_id, user_id = str(card.id), owner.id
    task_id = (await _start(async_client, card_id, user_id)).json()["optimization_task"]["id"]

    resp = await _launch(async_client, card_id, user_id)
    assert resp.status_code == 200
    assert resp.json()["optimization_task"]["status"] == "pending"
    assert len(await _jobs_for(db_session, task_id)) == 1

    again = await _launch(async_client, card_id, user_id)
    assert again.status_code == 409
    assert len(await _jobs_for(db_session, task_id)) == 1

    db_session.expire_all()
    status = (await db_session.execute(select(Task.status).where(Task.id == task_id))).scalar_one()
    assert status == "pending"


async def test_launch_without_task_is_404(async_client, db_session, project, card, owner):
    """Запускать нечего — этап пуст."""
    resp = await _launch(async_client, str(card.id), owner.id)
    assert resp.status_code == 404


async def test_estimate_stage_still_starts_immediately(
    async_client, db_session, project, card, owner
):
    """Правило только про оптимизацию: остальные стадии как были — сразу в очередь."""
    card_id, user_id, project_id = str(card.id), owner.id, str(project.id)
    resp = await async_client.post(
        f"/api/workflow-cards/{card_id}/start-task",
        data={"task_type": "ESTIMATE_FROM_LIST", "source_stage": "1"},
        headers=_auth(user_id),
    )
    assert resp.status_code == 400  # перечня у карточки нет — до очереди не дошло

    # Полноценный путь: карточка с готовым перечнем.
    list_task = Task(
        user_role="project_manager",
        owner_id=user_id,
        task_type="LIST_FROM_GRAND",
        status="completed",
        input_files=[],
        input_file_data=[],
        chat_history=[],
        progress_log=[],
        project_id=project_id,
    )
    db_session.add(list_task)
    await db_session.flush()
    fresh = await db_session.get(WorkflowCard, card_id)
    fresh.list_task_id = list_task.id
    fresh.estimate_task_id = None
    await db_session.commit()

    resp = await async_client.post(
        f"/api/workflow-cards/{card_id}/start-task",
        data={"task_type": "ESTIMATE_FROM_LIST", "source_stage": "1"},
        headers=_auth(user_id),
    )
    assert resp.status_code == 200
    est = resp.json()["estimate_task"]
    assert est["status"] == "pending"
    assert len(await _jobs_for(db_session, est["id"])) == 1
