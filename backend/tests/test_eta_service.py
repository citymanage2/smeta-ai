"""Фаза 3 ETA: длительность по объёму, калибровка по истории, симуляция очереди."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.config import settings
from app.models.task import Task
from app.services import eta_service
from app.services.eta_service import (
    Rates,
    TaskSnapshot,
    estimate_duration_s,
    remaining_s,
    simulate_queue,
)
from app.utils.volume_probe import UNIT_ITEMS, UNIT_ROWS

NOW = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
async def clean_tasks(db_session):
    """Тесты калибровки коммитят задачи, а откат сессии закоммиченное не убирает —
    без явной чистки история одного теста утекала бы в выборку следующего."""
    from sqlalchemy import text

    await db_session.execute(text("DELETE FROM tasks"))
    await db_session.commit()
    yield
    await db_session.execute(text("DELETE FROM tasks"))
    await db_session.commit()


def _snapshot(**kw) -> TaskSnapshot:
    """Прогноз работает с лёгким снимком задачи, а не с ORM-строкой."""
    return TaskSnapshot.from_task(_task(**kw))


def _task(**kw) -> Task:
    defaults = dict(
        id=str(uuid.uuid4()),
        user_role="user",
        task_type="ESTIMATE_FROM_LIST",
        status="pending",
        input_files=[],
        input_file_data=[],
        chat_history=[],
        processing_mode="fast",
        created_at=NOW,
    )
    defaults.update(kw)
    return Task(**defaults)


# --- длительность ----------------------------------------------------------

def test_duration_scales_with_volume():
    small = _task(volume_units=50, volume_kind=UNIT_ITEMS)
    big = _task(volume_units=1000, volume_kind=UNIT_ITEMS)

    small_s, _ = estimate_duration_s(small, Rates())
    big_s, _ = estimate_duration_s(big, Rates())

    assert big_s > small_s * 10


def test_duration_without_volume_falls_back_and_is_rough():
    total_s, rough = estimate_duration_s(_task(), Rates())
    assert total_s > 0
    assert rough is True


def test_batch_mode_uses_its_own_rate():
    """Пачка считается на серверах Anthropic — её тайминги отдельные."""
    rates = Rates(per_unit={
        ("ESTIMATE_FROM_LIST", "fast", UNIT_ITEMS): 20.0,
        ("ESTIMATE_FROM_LIST", "batch", UNIT_ITEMS): 2.0,
    })
    fast_s, _ = estimate_duration_s(
        _task(volume_units=500, volume_kind=UNIT_ITEMS, processing_mode="fast"), rates
    )
    batch_s, _ = estimate_duration_s(
        _task(volume_units=500, volume_kind=UNIT_ITEMS, processing_mode="batch"), rates
    )
    assert batch_s < fast_s


# --- остаток бегущей задачи ------------------------------------------------

def test_remaining_subtracts_elapsed():
    task = _snapshot(status="processing", started_at=NOW - timedelta(seconds=600))
    remaining, finishing = remaining_s(task, total_s=1000, now=NOW)
    assert remaining == pytest.approx(400)
    assert finishing is False


def test_overdue_task_reports_finishing():
    task = _snapshot(status="processing", started_at=NOW - timedelta(hours=6))
    remaining, finishing = remaining_s(task, total_s=1000, now=NOW)
    assert finishing is True
    assert remaining > 0  # никаких «через −5 часов»


def test_progress_counter_beats_the_model():
    """Задача отчиталась о 50% за час — значит остался примерно час,
    что бы ни думала модель."""
    task = _snapshot(
        status="processing",
        started_at=NOW - timedelta(hours=1),
        progress_data={"chunks_done": 5, "total_chunks": 10},
    )
    remaining, _ = remaining_s(task, total_s=100, now=NOW)
    assert remaining == pytest.approx(3600, rel=0.01)


def test_early_progress_is_not_trusted():
    """1 чанк из 100 — слишком мало, чтобы экстраполировать."""
    task = _snapshot(
        status="processing",
        started_at=NOW - timedelta(seconds=300),
        progress_data={"chunks_done": 1, "total_chunks": 100},
    )
    remaining, _ = remaining_s(task, total_s=1200, now=NOW)
    assert remaining == pytest.approx(900)


# --- симуляция очереди -----------------------------------------------------

def _flat(seconds: float) -> Rates:
    """Ставки, при которых любая задача без объёма считается ровно seconds."""
    return Rates(flat={("ESTIMATE_FROM_LIST", "fast"): seconds})


def test_pending_waits_for_a_free_slot():
    running = [
        _task(status="processing", started_at=NOW, id=f"run-{i}") for i in range(2)
    ]
    waiting = _task(status="pending", id="wait")

    eta = simulate_queue(running + [waiting], _flat(600), NOW, slots=2)

    assert eta["run-0"].starts_in_s == 0
    # Оба слота заняты на 600 с — ожидающая стартует после освобождения первого.
    assert eta["wait"].starts_in_s == pytest.approx(600, abs=2)
    assert eta["wait"].ready_in_s == pytest.approx(1200, abs=2)


def test_free_slots_start_immediately():
    tasks = [_task(status="pending", id="a"), _task(status="pending", id="b")]
    eta = simulate_queue(tasks, _flat(600), NOW, slots=4)
    assert eta["a"].starts_in_s == 0
    assert eta["b"].starts_in_s == 0


def test_batch_task_does_not_hold_a_worker_slot():
    """Пачка ждёт ответа Anthropic — воркер в это время свободен."""
    batch = _task(
        id="batch",
        status="processing",
        processing_mode="batch",
        started_at=NOW,
        progress_data={"_stage": "batch_pending", "batch_id": "b-1"},
    )
    waiting = _task(status="pending", id="wait")

    eta = simulate_queue([batch, waiting], _flat(600), NOW, slots=1)

    assert eta["wait"].starts_in_s == 0


def test_more_running_than_slots_is_conservative():
    running = [
        _task(status="processing", id=f"r{i}", started_at=NOW - timedelta(seconds=i * 60))
        for i in range(4)
    ]
    waiting = _task(status="pending", id="wait")
    eta = simulate_queue(running + [waiting], _flat(600), NOW, slots=1)
    # Держим самый поздний из занятых слотов, а не самый ранний.
    assert eta["wait"].starts_in_s == pytest.approx(eta["r0"].ready_in_s, abs=2)


def test_ready_at_matches_ready_in():
    eta = simulate_queue([_task(status="pending", id="a")], _flat(600), NOW, slots=1)["a"]
    ready_at = datetime.fromisoformat(eta.ready_at)
    assert (ready_at - NOW).total_seconds() == pytest.approx(eta.ready_in_s, abs=2)


# --- калибровка ------------------------------------------------------------

async def _seed_completed(db, count, *, units, seconds, task_type="ESTIMATE_FROM_LIST"):
    for i in range(count):
        finished = NOW - timedelta(hours=i + 1)
        db.add(Task(
            id=str(uuid.uuid4()),
            user_role="user",
            task_type=task_type,
            status="completed",
            input_files=[],
            input_file_data=[],
            chat_history=[],
            processing_mode="fast",
            volume_units=units,
            volume_kind=UNIT_ITEMS,
            started_at=finished - timedelta(seconds=seconds),
            finished_at=finished,
            created_at=finished - timedelta(seconds=seconds),
        ))
    await db.commit()


@pytest.mark.asyncio
async def test_too_little_history_keeps_defaults(db_session):
    await _seed_completed(db_session, 2, units=100, seconds=1240)
    rates = await eta_service.load_rates(db_session, now=NOW)
    assert rates.per_unit == {}

    _, rough = estimate_duration_s(
        _task(volume_units=100, volume_kind=UNIT_ITEMS), rates
    )
    assert rough is True


async def _waiting_estimate(db, units: int = 100) -> Task:
    """Новая смета из перечня на `units` позиций — одна в очереди."""
    task = _task(status="pending", volume_units=units, volume_kind=UNIT_ITEMS)
    db.add(task)
    await db.commit()
    return task


@pytest.mark.asyncio
async def test_history_calibrates_the_forecast(db_session):
    """Сметы на 100 позиций считались по 1240 с — новую такую же прогноз ждёт
    через ≈1240 с и больше не помечает грубой."""
    waiting = await _waiting_estimate(db_session)
    before = (await eta_service.queue_forecast(db_session, now=NOW))[waiting.id]
    assert before.rough is True  # истории нет — оценка честно грубая

    await _seed_completed(db_session, 4, units=100, seconds=1240)
    after = (await eta_service.queue_forecast(db_session, now=NOW))[waiting.id]

    assert after.rough is False
    assert after.ready_in_s == pytest.approx(1240, abs=30)  # прогноз — с точностью до минуты


@pytest.mark.asyncio
async def test_outlier_does_not_break_the_forecast(db_session):
    """Одна задача «висела» 20 часов из-за сбоя API — прогноз остаётся ≈1240 с."""
    await _seed_completed(db_session, 4, units=100, seconds=1240)
    await _seed_completed(db_session, 1, units=100, seconds=72000)
    waiting = await _waiting_estimate(db_session)

    eta = (await eta_service.queue_forecast(db_session, now=NOW))[waiting.id]

    assert eta.ready_in_s == pytest.approx(1240, abs=30)


@pytest.mark.asyncio
async def test_garbage_history_does_not_send_forecast_to_space(db_session):
    """Даже если ВСЯ выборка мусорная (позиция за 22 часа), смета на 100 позиций
    ждёт часы, а не месяцы."""
    await _seed_completed(db_session, 5, units=1, seconds=80000)
    waiting = await _waiting_estimate(db_session)

    eta = (await eta_service.queue_forecast(db_session, now=NOW))[waiting.id]

    assert eta.ready_in_s < 24 * 3600


@pytest.mark.asyncio
async def test_old_history_is_ignored(db_session):
    for i in range(5):
        finished = NOW - timedelta(days=60 + i)
        db_session.add(Task(
            id=str(uuid.uuid4()),
            user_role="user",
            task_type="ESTIMATE_FROM_LIST",
            status="completed",
            input_files=[],
            input_file_data=[],
            chat_history=[],
            processing_mode="fast",
            volume_units=100,
            volume_kind=UNIT_ITEMS,
            started_at=finished - timedelta(seconds=1240),
            finished_at=finished,
            created_at=finished,
        ))
    await db_session.commit()

    rates = await eta_service.load_rates(db_session, now=NOW)
    assert rates.per_unit == {}


@pytest.mark.asyncio
async def test_forecast_reads_progress_of_running_batch(db_session, monkeypatch):
    """Из progress_data прогноз берёт счётчики чанков и признак пачки, даже когда
    рядом лежит тяжёлый документ (позиции, OCR)."""
    monkeypatch.setattr(settings, "WORKER_CONCURRENCY", 1)
    heavy = {
        "_stage": "batch_pending",
        "batch_id": "msgbatch_1",
        "chunks_done": 8,
        "total_chunks": 10,
        "ocr_pages": ["очень много текста"] * 50,
    }
    batch = _task(
        status="processing",
        processing_mode="batch",
        started_at=NOW - timedelta(hours=1),
        progress_data=heavy,
    )
    waiting = _task(status="pending")
    db_session.add_all([batch, waiting])
    await db_session.commit()

    forecast = await eta_service.queue_forecast(db_session, now=NOW)

    # 8 из 10 чанков за час — осталась четверть часа, что бы ни думала модель.
    assert forecast[batch.id].ready_in_s == pytest.approx(900, abs=60)
    # Пачка слот не держит — ожидающая задача стартует сразу, хотя слот один.
    assert forecast[waiting.id].starts_in_s == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status", ["completed", "failed", "cancelled", "paused", "not_started"]
)
async def test_queue_forecast_covers_active_tasks_only(db_session, monkeypatch, status):
    """В прогнозе — только очередь и работа. Незапущенная оптимизация
    (`not_started`, правило №20) ждёт кнопки: в прогнозе её нет, и очередь перед
    ней не стоит — задача, поставленная позже, идёт первой."""
    monkeypatch.setattr(settings, "WORKER_CONCURRENCY", 1)
    inactive = _task(
        status=status, task_type="ESTIMATE_OPTIMIZATION", created_at=NOW - timedelta(minutes=30)
    )
    active = _task(status="pending", volume_units=100, volume_kind=UNIT_ROWS)
    db_session.add_all([inactive, active])
    await db_session.commit()

    forecast = await eta_service.queue_forecast(db_session, now=NOW)

    assert inactive.id not in forecast
    assert forecast[active.id].units == 100
    assert forecast[active.id].queue_position == 1
    assert forecast[active.id].starts_in_s == 0
