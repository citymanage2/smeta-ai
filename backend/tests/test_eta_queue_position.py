"""Место в очереди: сколько задач впереди до запуска.

Задачи считаются строго по одной (решение 30.07.2026: параллельная обработка на
этой машине не выживала). Тогда очередь становится настоящей очередью, и главный
вопрос пользователя — «меня когда возьмут». Минуты ожидания это оценка, а позиция
— факт, поэтому она отдаётся отдельным полем.

План: plans/2026-07-30-parallelnaya-obrabotka-umiraet.md, Фаза 8.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.task import Task
from app.services.eta_service import Rates, simulate_queue

NOW = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)


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


def _flat(seconds: float) -> Rates:
    """Ставки, при которых любая задача без объёма считается ровно `seconds`."""
    return Rates(flat={("ESTIMATE_FROM_LIST", "fast"): seconds})


def test_positions_follow_queue_order():
    tasks = [
        _task(id="c", created_at=NOW - timedelta(minutes=1)),
        _task(id="a", created_at=NOW - timedelta(minutes=30)),
        _task(id="b", created_at=NOW - timedelta(minutes=10)),
    ]

    eta = simulate_queue(tasks, _flat(600), NOW, slots=1)

    assert eta["a"].queue_position == 1
    assert eta["b"].queue_position == 2
    assert eta["c"].queue_position == 3


def test_running_task_has_no_position():
    """У считающейся задачи позиции нет по смыслу — она уже не в очереди."""
    tasks = [
        _task(id="run", status="processing", started_at=NOW - timedelta(minutes=2)),
        _task(id="wait"),
    ]

    eta = simulate_queue(tasks, _flat(600), NOW, slots=1)

    assert eta["run"].queue_position is None
    assert eta["wait"].queue_position == 1


def test_position_matches_growing_wait():
    """Позиция и ожидание согласованы: третья ждёт дольше второй."""
    tasks = [_task(id=f"t{i}", created_at=NOW - timedelta(minutes=10 - i)) for i in range(3)]

    eta = simulate_queue(tasks, _flat(600), NOW, slots=1)

    ordered = sorted(eta.values(), key=lambda e: e.queue_position)
    assert [e.queue_position for e in ordered] == [1, 2, 3]
    assert ordered[0].starts_in_s == 0
    assert ordered[1].starts_in_s == pytest.approx(600, abs=2)
    assert ordered[2].starts_in_s == pytest.approx(1200, abs=2)
    # И результат каждой следующей дальше — очередь последовательная.
    assert ordered[0].ready_in_s < ordered[1].ready_in_s < ordered[2].ready_in_s


def test_single_task_is_next_in_line():
    eta = simulate_queue([_task(id="only")], _flat(600), NOW, slots=1)

    assert eta["only"].queue_position == 1
    assert eta["only"].starts_in_s == 0


def test_default_slots_are_sequential():
    """Без явных слотов берётся настройка — а она теперь «одна задача за раз».

    Если web разойдётся с обработчиком, прогноз соврёт: покажет «старт вот-вот»
    там, где на самом деле час ожидания.
    """
    from app.config import settings

    assert settings.WORKER_CONCURRENCY == 1

    tasks = [_task(id="a", created_at=NOW - timedelta(minutes=5)), _task(id="b")]
    eta = simulate_queue(tasks, _flat(600), NOW)

    assert eta["a"].queue_position == 1
    assert eta["b"].queue_position == 2
    assert eta["b"].starts_in_s == pytest.approx(600, abs=2)
