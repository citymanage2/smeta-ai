"""Агрегатор затрат и таймингов задачи — точные числа.

План: `plans/2026-08-06-metriki-zatrat-po-stadiyam.md`, Фаза 3.

Ошибка в этих цифрах стоит дешевле ошибки в смете, но врать они не должны:
по ним принимается решение «во что нам обходится тендер». Поэтому здесь всё
проверяется точными значениями, а не «больше нуля».
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.models.api_call_log import ApiCallLog
from app.models.task import Task
from app.models.workflow_card import WorkflowCard  # noqa: F401  (метаданные таблиц)
from app.services.usage_metrics import timings_for_task, usage_for_tasks

NOW = datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc)


def _task(**kwargs) -> Task:
    base = dict(
        user_role="project_manager",
        task_type="ESTIMATE_FROM_LIST",
        status="completed",
        input_files=[],
        input_file_data=[],
        chat_history=[],
        progress_log=[],
        created_at=NOW - timedelta(minutes=20),
        started_at=NOW - timedelta(minutes=17),
        finished_at=NOW - timedelta(minutes=3),
        updated_at=NOW,
    )
    base.update(kwargs)
    return Task(**base)


def _call(task_id: str, *, tokens: tuple[int, int, int, int], cost: str, extra: bool):
    inp, out, cache_read, cache_creation = tokens
    return ApiCallLog(
        task_id=task_id,
        model="claude-test",
        input_tokens=inp,
        output_tokens=out,
        cache_read_tokens=cache_read,
        cache_creation_tokens=cache_creation,
        cost_usd=Decimal(cost),
        is_extra=extra,
        called_at=NOW,
    )


# ---------------------------------------------------------------------------
# Тайминги — чистая функция, без БД
# ---------------------------------------------------------------------------

def test_queue_and_work_seconds_from_timestamps():
    """Очередь — до старта, работа — от старта до финиша."""
    q, w, q_run, w_run = timings_for_task(_task(), now=NOW)
    assert q == 180.0          # 20 мин ожидания − 17 мин от старта
    assert w == 14 * 60.0      # 17 мин − 3 мин
    assert (q_run, w_run) == (False, False)


def test_waiting_task_queue_grows_to_now():
    """Задача ещё в очереди → ожидание считается до «сейчас» и помечено растущим."""
    task = _task(status="pending", started_at=None, finished_at=None)
    q, w, q_run, w_run = timings_for_task(task, now=NOW)
    assert q == 20 * 60.0
    assert q_run is True
    assert w is None and w_run is False


def test_growing_counters_are_rounded_down_to_a_minute():
    """Растущее значение округлено до минуты — иначе ETag ломался бы на каждом опросе."""
    task = _task(
        status="pending",
        created_at=NOW - timedelta(minutes=3, seconds=47),
        started_at=None,
        finished_at=None,
    )
    q, _, q_run, _ = timings_for_task(task, now=NOW)
    assert q == 180.0 and q_run is True

    running = _task(
        status="processing",
        started_at=NOW - timedelta(minutes=2, seconds=30),
        finished_at=None,
    )
    _, w, _, w_run = timings_for_task(running, now=NOW)
    assert w == 120.0 and w_run is True


def test_finished_counters_keep_exact_seconds():
    """Завершённое значение не меняется — огрублять его незачем."""
    task = _task(
        created_at=NOW - timedelta(minutes=5),
        started_at=NOW - timedelta(minutes=4, seconds=15),
        finished_at=NOW - timedelta(minutes=1, seconds=5),
    )
    q, w, _, _ = timings_for_task(task, now=NOW)
    assert q == 45.0
    assert w == 190.0


def test_running_task_work_grows_to_now():
    """Задача идёт → работа считается до «сейчас», ожидание уже зафиксировано."""
    task = _task(status="processing", finished_at=None)
    q, w, q_run, w_run = timings_for_task(task, now=NOW)
    assert q == 180.0 and q_run is False
    assert w == 17 * 60.0 and w_run is True


def test_never_started_and_inactive_gives_no_numbers():
    """Отменённая до старта не показывает ноль: нуля работы не было, было ничего."""
    task = _task(status="cancelled", started_at=None, finished_at=None)
    assert timings_for_task(task, now=NOW) == (None, None, False, False)


def test_started_but_abandoned_does_not_grow():
    """Оборвалась на рестарте: время не дорисовывается — она давно не работает."""
    task = _task(status="failed", finished_at=None)
    q, w, q_run, w_run = timings_for_task(task, now=NOW)
    assert q == 180.0
    assert w is None and w_run is False


def test_naive_timestamps_are_treated_as_utc():
    """SQLite отдаёт наивные datetime — расчёт не должен падать на смешении зон."""
    task = _task(
        created_at=NOW.replace(tzinfo=None) - timedelta(minutes=10),
        started_at=NOW.replace(tzinfo=None) - timedelta(minutes=8),
        finished_at=NOW.replace(tzinfo=None) - timedelta(minutes=1),
    )
    q, w, _, _ = timings_for_task(task, now=NOW)
    assert q == 120.0
    assert w == 7 * 60.0


# ---------------------------------------------------------------------------
# Агрегация журнала вызовов
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_main_and_extra_are_summed_separately(db_session):
    """Основная обработка и допы — две независимые суммы, не перемешиваются."""
    task = _task()
    db_session.add(task)
    await db_session.flush()

    db_session.add_all([
        _call(task.id, tokens=(1000, 200, 50, 10), cost="1.500000", extra=False),
        _call(task.id, tokens=(2000, 300, 0, 0), cost="2.250000", extra=False),
        _call(task.id, tokens=(100, 20, 5, 0), cost="0.400000", extra=True),
    ])
    await db_session.commit()

    usage = await usage_for_tasks(db_session, [task], now=NOW)
    u = usage[str(task.id)]

    # 1000+200+50+10 + 2000+300 = 3560
    assert u.tokens == 3560
    assert u.cost_usd == 3.75
    # 100+20+5 = 125
    assert u.extra_tokens == 125
    assert u.extra_cost_usd == 0.4


@pytest.mark.asyncio
async def test_all_four_token_kinds_counted(db_session):
    """Кэш даёт большую часть счёта — потерять cache_creation нельзя."""
    task = _task()
    db_session.add(task)
    await db_session.flush()
    db_session.add(_call(task.id, tokens=(1, 2, 4, 8), cost="0.000015", extra=False))
    await db_session.commit()

    usage = await usage_for_tasks(db_session, [task], now=NOW)
    assert usage[str(task.id)].tokens == 15


@pytest.mark.asyncio
async def test_task_without_any_calls_present_with_zeros(db_session):
    """Файл загрузили руками — задача в ответе есть, но денег на ней нет."""
    task = _task()
    db_session.add(task)
    await db_session.commit()

    usage = await usage_for_tasks(db_session, [task], now=NOW)
    u = usage[str(task.id)]
    assert (u.tokens, u.cost_usd, u.extra_tokens, u.extra_cost_usd) == (0, 0.0, 0, 0.0)


@pytest.mark.asyncio
async def test_calls_of_other_tasks_do_not_leak(db_session):
    """Чужие вызовы не попадают в чужую смету."""
    mine, alien = _task(), _task()
    db_session.add_all([mine, alien])
    await db_session.flush()
    db_session.add_all([
        _call(mine.id, tokens=(10, 0, 0, 0), cost="0.100000", extra=False),
        _call(alien.id, tokens=(999, 0, 0, 0), cost="9.000000", extra=False),
    ])
    await db_session.commit()

    usage = await usage_for_tasks(db_session, [mine], now=NOW)
    assert set(usage) == {str(mine.id)}
    assert usage[str(mine.id)].tokens == 10


@pytest.mark.asyncio
async def test_several_runs_sum_tokens_but_time_is_of_the_last(db_session):
    """Перезапуск: деньги за оба прогона, время — только последнего прогона."""
    task = _task()
    db_session.add(task)
    await db_session.flush()
    db_session.add_all([
        _call(task.id, tokens=(500, 100, 0, 0), cost="0.600000", extra=False),
        _call(task.id, tokens=(500, 100, 0, 0), cost="0.600000", extra=False),
    ])
    await db_session.commit()

    u = (await usage_for_tasks(db_session, [task], now=NOW))[str(task.id)]
    assert u.tokens == 1200
    assert u.cost_usd == 1.2
    assert u.work_seconds == 14 * 60.0


@pytest.mark.asyncio
async def test_empty_input_does_not_touch_db(db_session):
    """Ни одной задачи — ни одного запроса: доска без карточек не платит за SQL."""
    assert await usage_for_tasks(db_session, [], now=NOW) == {}
    assert await usage_for_tasks(db_session, [None], now=NOW) == {}


@pytest.mark.asyncio
async def test_single_query_for_many_tasks(db_session):
    """AC-9: число запросов не растёт с числом задач."""
    tasks = [_task() for _ in range(5)]
    db_session.add_all(tasks)
    await db_session.flush()
    for t in tasks:
        db_session.add(_call(t.id, tokens=(10, 10, 0, 0), cost="0.020000", extra=False))
    await db_session.commit()

    executed: list[str] = []
    original = db_session.execute

    async def counting_execute(statement, *args, **kwargs):
        executed.append(str(statement))
        return await original(statement, *args, **kwargs)

    db_session.execute = counting_execute  # type: ignore[method-assign]
    try:
        usage = await usage_for_tasks(db_session, tasks, now=NOW)
    finally:
        db_session.execute = original  # type: ignore[method-assign]

    assert len(usage) == 5
    assert len(executed) == 1
