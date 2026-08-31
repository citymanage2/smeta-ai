"""Карточки «Пульса сегодня» кликабельны: под каждой — свой список задач.

План: `plans/2026-08-31-klikabelnye-kartochki-pulsa.md`.

Главное, что здесь закреплено, — совпадение цифры на карточке с числом строк в
таблице под ней. Оба берутся из `_pulse_conditions`, и разъехаться они могут
только если кто-то заведёт условия во втором месте.
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio

from app.models.api_call_log import ApiCallLog
from app.models.project import Project
from app.models.task import Task

NOW = datetime.now(timezone.utc)
TODAY_START = NOW.replace(hour=0, minute=0, second=0, microsecond=0)
YESTERDAY = TODAY_START - timedelta(hours=5)


def _task(**over) -> Task:
    base = dict(
        id=str(uuid.uuid4()),
        user_role="admin",
        task_type="ESTIMATE_FROM_LIST",
        status="completed",
        input_files=[],
        input_file_data=[],
        chat_history=[],
        progress_log=[],
        created_at=TODAY_START + timedelta(hours=1),
        updated_at=TODAY_START + timedelta(hours=2),
    )
    base.update(over)
    return Task(**base)


@pytest_asyncio.fixture
async def project(db_session) -> Project:
    proj = Project(name="Пульс-проект")
    db_session.add(proj)
    await db_session.commit()
    await db_session.refresh(proj)
    return proj


async def _pulse(async_client, admin_token) -> dict:
    resp = await async_client.get(
        "/dashboard/stats", headers={"Authorization": admin_token}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["pulse"]


async def _bucket(async_client, admin_token, bucket: str) -> dict:
    resp = await async_client.get(
        f"/dashboard/pulse/{bucket}", headers={"Authorization": admin_token}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_bucket_row_carries_project_time_tokens_and_cost(
    async_client, admin_token, db_session, project
):
    """Строка таблицы — ровно те пять колонок, ради которых всё делалось."""
    task = _task(
        project_id=project.id,
        name="Смета АР",
        started_at=TODAY_START + timedelta(hours=1),
        finished_at=TODAY_START + timedelta(hours=1, minutes=14),
    )
    db_session.add(task)
    await db_session.flush()
    db_session.add_all([
        ApiCallLog(
            task_id=task.id, model="m", input_tokens=1000, output_tokens=200,
            cache_read_tokens=0, cache_creation_tokens=0,
            cost_usd=Decimal("1.250000"), is_extra=False, called_at=NOW,
        ),
        # Доп-запрос человека по готовому файлу: в строку он входит наравне с
        # основными — пользователь смотрит, во что обошлась задача целиком.
        ApiCallLog(
            task_id=task.id, model="m", input_tokens=300, output_tokens=0,
            cache_read_tokens=0, cache_creation_tokens=0,
            cost_usd=Decimal("0.500000"), is_extra=True, called_at=NOW,
        ),
    ])
    await db_session.commit()

    data = await _bucket(async_client, admin_token, "completed")
    row = next(r for r in data["tasks"] if r["id"] == task.id)

    assert row["project_name"] == "Пульс-проект"
    assert row["name"] == "Смета АР"
    assert row["task_type"] == "ESTIMATE_FROM_LIST"
    assert row["work_seconds"] == 14 * 60.0
    assert row["tokens"] == 1500
    assert row["cost_usd"] == 1.75


@pytest.mark.asyncio
async def test_totals_are_sum_of_rows(async_client, admin_token, db_session):
    """Итоги над таблицей — сумма строк, а не отдельный запрос со своей правдой."""
    for cost, tokens in (("2.000000", 100), ("0.250000", 400)):
        task = _task(
            started_at=TODAY_START + timedelta(hours=1),
            finished_at=TODAY_START + timedelta(hours=1, minutes=5),
        )
        db_session.add(task)
        await db_session.flush()
        db_session.add(ApiCallLog(
            task_id=task.id, model="m", input_tokens=tokens, output_tokens=0,
            cache_read_tokens=0, cache_creation_tokens=0,
            cost_usd=Decimal(cost), is_extra=False, called_at=NOW,
        ))
    await db_session.commit()

    data = await _bucket(async_client, admin_token, "completed")

    assert data["count"] == len(data["tasks"])
    assert data["total_tokens"] == sum(r["tokens"] for r in data["tasks"])
    assert data["total_cost_usd"] == pytest.approx(sum(r["cost_usd"] for r in data["tasks"]))
    assert data["total_work_seconds"] == pytest.approx(
        sum(r["work_seconds"] or 0 for r in data["tasks"])
    )


@pytest.mark.asyncio
async def test_counter_equals_row_count_for_every_bucket(
    async_client, admin_token, db_session
):
    """Цифра на карточке = число строк под ней. Пять карточек, пять проверок."""
    db_session.add_all([
        _task(status="processing", started_at=NOW - timedelta(minutes=3), finished_at=None),
        _task(status="pending", started_at=None, finished_at=None),
        _task(status="completed", finished_at=TODAY_START + timedelta(hours=3)),
        _task(status="failed", finished_at=TODAY_START + timedelta(hours=4)),
        # Вчерашняя и вчера же закрытая — не попадает ни в одну «сегодняшнюю».
        _task(
            status="completed",
            created_at=YESTERDAY,
            updated_at=YESTERDAY,
            finished_at=YESTERDAY,
        ),
    ])
    await db_session.commit()

    pulse = await _pulse(async_client, admin_token)
    counters = {
        "created": pulse["created_today"],
        "processing": pulse["processing_now"],
        "pending": pulse["pending_now"],
        "completed": pulse["completed_today"],
        "failed": pulse["failed_today"],
    }
    for bucket, counter in counters.items():
        data = await _bucket(async_client, admin_token, bucket)
        assert data["count"] == counter, bucket
        assert len(data["tasks"]) == counter, bucket


@pytest.mark.asyncio
async def test_finished_today_counts_yesterdays_task(
    async_client, admin_token, db_session
):
    """Запущена вчера, упала сегодня — это сегодняшняя ошибка.

    До 31.08.2026 счётчик фильтровал по `created_at`, и ночные падения в
    «С ошибкой сегодня» не попадали вовсе.
    """
    task = _task(
        status="failed",
        created_at=YESTERDAY,
        started_at=YESTERDAY,
        finished_at=TODAY_START + timedelta(minutes=30),
        error_message="Оборвалось",
    )
    db_session.add(task)
    await db_session.commit()

    # Таблицы живут весь прогон, поэтому смотрим на свою задачу, а не на общий
    # счётчик: соседний тест мог добавить свои падения.
    failed_ids = [r["id"] for r in (await _bucket(async_client, admin_token, "failed"))["tasks"]]
    created_ids = [r["id"] for r in (await _bucket(async_client, admin_token, "created"))["tasks"]]
    assert task.id in failed_ids
    assert task.id not in created_ids


@pytest.mark.asyncio
async def test_legacy_task_without_finished_at_still_counted(
    async_client, admin_token, db_session
):
    """Задача, завершённая до появления `finished_at`, не исчезает из карточки."""
    task = _task(status="completed", finished_at=None, updated_at=TODAY_START + timedelta(hours=6))
    db_session.add(task)
    await db_session.commit()

    data = await _bucket(async_client, admin_token, "completed")
    row = next(r for r in data["tasks"] if r["id"] == task.id)
    # Время не выдумывается: старта не было — прочерк, а не ноль.
    assert row["work_seconds"] is None


@pytest.mark.asyncio
async def test_deleted_task_is_invisible(async_client, admin_token, db_session):
    """Удалённая задача не считается и не показывается — как и во всём дашборде."""
    task = _task(status="failed", finished_at=NOW, deleted_at=NOW)
    db_session.add(task)
    await db_session.commit()

    data = await _bucket(async_client, admin_token, "failed")
    assert task.id not in [r["id"] for r in data["tasks"]]


@pytest.mark.asyncio
async def test_unknown_bucket_is_404(async_client, admin_token):
    resp = await async_client.get(
        "/dashboard/pulse/whatever", headers={"Authorization": admin_token}
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_bucket_requires_manager(async_client, user_token):
    """Дашборд — управленческий раздел; список задач под карточкой тоже."""
    resp = await async_client.get(
        "/dashboard/pulse/created", headers={"Authorization": user_token}
    )
    assert resp.status_code == 403
