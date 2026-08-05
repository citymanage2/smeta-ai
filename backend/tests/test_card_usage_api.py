"""Метрики затрат едут в уже поллящемся ответе списка карточек.

План: `plans/2026-08-06-metriki-zatrat-po-stadiyam.md`, Фаза 4.

Отдельного endpoint'а под метрики нет намеренно: список карточек проекта фронт
и так тянет каждые 5 секунд, и второй поллинг рядом с ним — чистая трата.
Отсюда же главное требование теста: число SQL-запросов не должно расти вместе
с числом смет в проекте.
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio

from app.models.api_call_log import ApiCallLog
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.models.workflow_card import WorkflowCard
from app.utils.auth import create_access_token, hash_password

NOW = datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc)


def _auth(user_id: int, role: str = "project_manager") -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id, role)}"}


@pytest_asyncio.fixture
async def owner(db_session) -> User:
    user = User(
        # Таблицы живут весь прогон — логин уникален, иначе второй тест упрётся
        # в UNIQUE constraint на users.username.
        username=f"metrics-{uuid.uuid4().hex[:8]}",
        full_name="Метрикин М.М.",
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
    proj = Project(name="Метрики", owner_id=owner.id)
    db_session.add(proj)
    await db_session.commit()
    await db_session.refresh(proj)
    return proj


async def _make_card(db_session, project, owner, *, name: str, cost=None) -> WorkflowCard:
    """Смета со стадией «смета»: задача + карточка, ссылающаяся на неё."""
    task = Task(
        user_role="project_manager",
        owner_id=owner.id,
        task_type="ESTIMATE_FROM_LIST",
        status="completed",
        input_files=[],
        input_file_data=[],
        chat_history=[],
        progress_log=[],
        project_id=project.id,
        cost=cost,
        created_at=NOW - timedelta(minutes=20),
        started_at=NOW - timedelta(minutes=17),
        finished_at=NOW - timedelta(minutes=3),
    )
    db_session.add(task)
    await db_session.flush()

    card = WorkflowCard(
        project_id=project.id, name=name, stage="estimate", estimate_task_id=task.id
    )
    db_session.add(card)
    await db_session.commit()
    return card


def _log(task_id: str, *, tokens: int, cost: str, extra: bool) -> ApiCallLog:
    return ApiCallLog(
        task_id=task_id,
        model="claude-test",
        input_tokens=tokens,
        output_tokens=0,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        cost_usd=Decimal(cost),
        is_extra=extra,
        called_at=NOW,
    )


@pytest.mark.asyncio
async def test_card_list_carries_stage_usage(async_client, db_session, project, owner):
    """Стадия отдаёт токены, деньги, тайминги и отдельно — допы."""
    card = await _make_card(db_session, project, owner, name="АР")
    db_session.add_all([
        _log(card.estimate_task_id, tokens=1000, cost="1.250000", extra=False),
        _log(card.estimate_task_id, tokens=200, cost="0.500000", extra=True),
    ])
    await db_session.commit()

    resp = await async_client.get(
        f"/api/projects/{project.id}/workflow-cards", headers=_auth(owner.id)
    )
    assert resp.status_code == 200
    usage = resp.json()[0]["estimate_task"]["usage"]

    assert usage["tokens"] == 1000
    assert usage["cost_usd"] == 1.25
    assert usage["extra_tokens"] == 200
    assert usage["extra_cost_usd"] == 0.5
    assert usage["queue_seconds"] == 180.0
    assert usage["work_seconds"] == 14 * 60.0
    assert usage["queue_running"] is False and usage["work_running"] is False


@pytest.mark.asyncio
async def test_stage_without_ai_calls_reports_zeros(async_client, db_session, project, owner):
    """Файл загрузили руками — метрики есть, но нулевые (не null и не мусор)."""
    await _make_card(db_session, project, owner, name="КЖ")

    resp = await async_client.get(
        f"/api/projects/{project.id}/workflow-cards", headers=_auth(owner.id)
    )
    usage = resp.json()[0]["estimate_task"]["usage"]
    assert usage["tokens"] == 0 and usage["cost_usd"] == 0.0
    assert usage["extra_tokens"] == 0 and usage["extra_cost_usd"] == 0.0


@pytest.mark.asyncio
async def test_card_list_carries_estimate_sum(async_client, db_session, project, owner):
    """Сумма сформированной сметы в рублях — та, из которой строится колонка «Сумма»."""
    await _make_card(db_session, project, owner, name="ОВ", cost=Decimal("1234567.89"))

    resp = await async_client.get(
        f"/api/projects/{project.id}/workflow-cards", headers=_auth(owner.id)
    )
    assert resp.json()[0]["estimate_task"]["cost"] == 1234567.89


@pytest.mark.asyncio
async def test_queries_do_not_grow_with_card_count(async_client, db_session, project, owner):
    """AC-9: пять смет стоят столько же запросов к журналу затрат, сколько одна."""
    from app.services import usage_metrics

    for i in range(5):
        card = await _make_card(db_session, project, owner, name=f"Смета {i}")
        db_session.add(_log(card.estimate_task_id, tokens=100, cost="0.100000", extra=False))
    await db_session.commit()

    calls: list[int] = []
    original = usage_metrics.usage_for_tasks

    async def counting(db, tasks, now=None):
        tasks = list(tasks)
        calls.append(len(tasks))
        return await original(db, tasks, now=now)

    usage_metrics.usage_for_tasks = counting
    try:
        resp = await async_client.get(
            f"/api/projects/{project.id}/workflow-cards", headers=_auth(owner.id)
        )
    finally:
        usage_metrics.usage_for_tasks = original

    assert resp.status_code == 200
    assert len(resp.json()) == 5
    # Один вызов агрегатора на весь список, а не по карточке.
    assert calls == [5]


@pytest.mark.asyncio
async def test_etag_still_short_circuits_unchanged_list(async_client, db_session, project, owner):
    """Метрики в теле не должны сломать 304: без изменений — тот же ETag."""
    await _make_card(db_session, project, owner, name="ЭОМ")

    first = await async_client.get(
        f"/api/projects/{project.id}/workflow-cards", headers=_auth(owner.id)
    )
    etag = first.headers["ETag"]

    second = await async_client.get(
        f"/api/projects/{project.id}/workflow-cards",
        headers={**_auth(owner.id), "If-None-Match": etag},
    )
    assert second.status_code == 304
