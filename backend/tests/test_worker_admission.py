"""Приём задач: по реальной памяти контейнера и с разносом захватов.

Почему это появилось: 30.07.2026 три возобновлённые задачи захватывались за 2–4
секунды (опрос очереди раз в 2 с), тормоз по памяти смотрел на ТЕКУЩУЮ занятость —
а она в первые секунды ещё низкая — и не срабатывал ни разу. Контейнер получал
OOM-kill. Лечится двумя вещами: доля от реального лимита (cgroup) вместо константы
в мегабайтах и пауза между захватами.

План: plans/2026-07-30-parallelnaya-obrabotka-umiraet.md, Фаза 3.
"""
import asyncio

import pytest

from app import worker
from app.config import settings
from app.utils.memory import MemorySnapshot

pytestmark = pytest.mark.asyncio


def _snap(monkeypatch, rss=None, usage=None, limit=None, source=None, available=None):
    """Подменить измерение памяти.

    `source='cgroup'` — у контейнера есть личный лимит; `source='host'` — лимита
    нет, цифра относится ко всей машине, и запас показывает только `available`
    (ровно так на проде 30.07.2026).
    """
    if source is None and limit is not None:
        source = "cgroup"
    monkeypatch.setattr(
        worker, "memory_snapshot",
        lambda: MemorySnapshot(
            rss_mb=rss, usage_mb=usage, limit_mb=limit,
            limit_source=source, available_mb=available,
        ),
    )


# ---------------------------------------------------------------------------
# Тормоз по доле лимита контейнера
# ---------------------------------------------------------------------------

async def test_brake_on_by_container_ratio(monkeypatch):
    """Занято 85% лимита контейнера — новую задачу не берём.

    Запас по мегабайтам выключен: срабатывать должна именно доля лимита.
    """
    monkeypatch.setattr(settings, "WORKER_MEM_HIGH_RATIO", 0.8)
    monkeypatch.setattr(settings, "WORKER_MEM_MIN_FREE_MB", 0)
    monkeypatch.setattr(settings, "WORKER_RSS_PAUSE_MB", 99999)
    monkeypatch.setattr(worker, "_inflight_job_ids", {1})
    _snap(monkeypatch, rss=900.0, usage=1740.0, limit=2048.0)

    assert worker._memory_brake_engaged() is True


async def test_brake_off_below_ratio(monkeypatch):
    """Половина лимита занята — параллельность работает, как и задумано."""
    monkeypatch.setattr(settings, "WORKER_MEM_HIGH_RATIO", 0.8)
    monkeypatch.setattr(settings, "WORKER_RSS_PAUSE_MB", 99999)
    monkeypatch.setattr(worker, "_inflight_job_ids", {1})
    _snap(monkeypatch, rss=700.0, usage=1024.0, limit=2048.0)

    assert worker._memory_brake_engaged() is False


async def test_absolute_rss_threshold_still_works_without_cgroup(monkeypatch):
    """cgroup недоступна (локально) — работает прежний порог в мегабайтах."""
    monkeypatch.setattr(settings, "WORKER_MEM_HIGH_RATIO", 0.8)
    monkeypatch.setattr(settings, "WORKER_RSS_PAUSE_MB", 1536)
    monkeypatch.setattr(worker, "_inflight_job_ids", {1})
    _snap(monkeypatch, rss=1600.0, usage=None, limit=None)

    assert worker._memory_brake_engaged() is True


async def test_brake_off_when_idle_even_if_over_ratio(monkeypatch):
    """Пустой процесс не тормозим никогда: иначе очередь заперта навсегда."""
    monkeypatch.setattr(settings, "WORKER_MEM_HIGH_RATIO", 0.8)
    monkeypatch.setattr(worker, "_inflight_job_ids", set())
    _snap(monkeypatch, rss=2000.0, usage=2000.0, limit=2048.0)

    assert worker._memory_brake_engaged() is False


# ---------------------------------------------------------------------------
# Общая машина без личного лимита контейнера — случай прода 30.07.2026
# ---------------------------------------------------------------------------

async def test_brake_on_when_host_memory_almost_gone(monkeypatch):
    """Лимита у контейнера нет, свободного на машине мало — не берём новую задачу.

    Диагностика 30.07.2026 показала «лимит 3911.8 МБ» — это была память ВСЕЙ
    машины (её делят web и обработчик), поэтому доля от лимита ничего не значила.
    Честный признак тесноты здесь — MemAvailable.
    """
    monkeypatch.setattr(settings, "WORKER_MEM_MIN_FREE_MB", 512)
    monkeypatch.setattr(settings, "WORKER_RSS_PAUSE_MB", 0)
    monkeypatch.setattr(worker, "_inflight_job_ids", {1})
    _snap(monkeypatch, rss=600.0, usage=None, limit=3911.8, source="host", available=300.0)

    assert worker._memory_brake_engaged() is True


async def test_brake_off_when_host_has_room(monkeypatch):
    """Свободной памяти вдоволь — параллельность работает."""
    monkeypatch.setattr(settings, "WORKER_MEM_MIN_FREE_MB", 512)
    monkeypatch.setattr(settings, "WORKER_RSS_PAUSE_MB", 0)
    monkeypatch.setattr(worker, "_inflight_job_ids", {1})
    _snap(monkeypatch, rss=600.0, usage=None, limit=3911.8, source="host", available=2500.0)

    assert worker._memory_brake_engaged() is False


async def test_brake_on_when_cgroom_headroom_small(monkeypatch):
    """С личным лимитом запас считается как «лимит минус занятое»."""
    monkeypatch.setattr(settings, "WORKER_MEM_MIN_FREE_MB", 512)
    monkeypatch.setattr(settings, "WORKER_MEM_HIGH_RATIO", 0.95)
    monkeypatch.setattr(settings, "WORKER_RSS_PAUSE_MB", 0)
    monkeypatch.setattr(worker, "_inflight_job_ids", {1})
    _snap(monkeypatch, rss=1700.0, usage=1800.0, limit=2048.0, source="cgroup")

    assert worker._memory_brake_engaged() is True


# ---------------------------------------------------------------------------
# Разнос захватов
# ---------------------------------------------------------------------------

async def test_stagger_blocks_second_claim_right_after_first(monkeypatch):
    """Вторая задача не берётся в первые секунды: память первой ещё не видна.

    Ровно этот случай ломал прод — три задачи разом.
    """
    monkeypatch.setattr(settings, "WORKER_CLAIM_STAGGER_S", 60)
    monkeypatch.setattr(worker, "_inflight_job_ids", {1})
    monkeypatch.setattr(worker, "_inflight_started_at", {1: 1000.0})
    monkeypatch.setattr(worker, "_monotonic", lambda: 1003.0)

    assert worker._claim_stagger_blocked() is True


async def test_stagger_allows_after_gap(monkeypatch):
    """Пауза выдержана — параллельность разрешена."""
    monkeypatch.setattr(settings, "WORKER_CLAIM_STAGGER_S", 60)
    monkeypatch.setattr(worker, "_inflight_job_ids", {1})
    monkeypatch.setattr(worker, "_inflight_started_at", {1: 1000.0})
    monkeypatch.setattr(worker, "_monotonic", lambda: 1075.0)

    assert worker._claim_stagger_blocked() is False


async def test_stagger_looks_at_youngest_job(monkeypatch):
    """Смотрим на самую свежую задачу, а не на самую старую."""
    monkeypatch.setattr(settings, "WORKER_CLAIM_STAGGER_S", 60)
    monkeypatch.setattr(worker, "_inflight_started_at", {1: 100.0, 2: 1000.0})
    monkeypatch.setattr(worker, "_monotonic", lambda: 1010.0)

    assert worker._claim_stagger_blocked() is True


async def test_stagger_never_blocks_first_claim(monkeypatch):
    """Первую задачу берём мгновенно: пустой обработчик ждать нечего."""
    monkeypatch.setattr(settings, "WORKER_CLAIM_STAGGER_S", 60)
    monkeypatch.setattr(worker, "_inflight_started_at", {})

    assert worker._claim_stagger_blocked() is False


async def test_stagger_disabled_by_zero(monkeypatch):
    monkeypatch.setattr(settings, "WORKER_CLAIM_STAGGER_S", 0)
    monkeypatch.setattr(worker, "_inflight_started_at", {1: 1000.0})
    monkeypatch.setattr(worker, "_monotonic", lambda: 1000.5)

    assert worker._claim_stagger_blocked() is False


@pytest.mark.parametrize("closed_by", ["stagger", "memory"])
async def test_second_job_waits_in_queue_while_admission_closed(worker_loop, monkeypatch, closed_by):
    """Первая задача ещё молодая (разнос) или памяти мало (тормоз) — вторая ждёт.

    Ждёт в очереди и не теряется: как только первая доиграла, вторую берут.
    """
    if closed_by == "stagger":
        monkeypatch.setattr(settings, "WORKER_CLAIM_STAGGER_S", 60)
    else:
        # Личный лимит 2 ГБ, занято 1,9 ГБ — запас меньше WORKER_MEM_MIN_FREE_MB.
        worker_loop.memory(usage=1900.0, limit=2048.0)
    held = worker_loop.hold("test.slow")
    await worker_loop.enqueue("test.slow", {"task_id": "A"})
    await worker_loop.enqueue("test.slow", {"task_id": "B"})

    async with worker_loop.running(slots=2):
        await held.wait_started(1)
        await asyncio.sleep(0.2)  # два десятка опросов очереди
        assert sorted((await worker_loop.statuses()).values()) == ["queued", "running"]

        held.release()
        for job_id in await worker_loop.statuses():
            await worker_loop.wait_status(job_id, "done")

    assert len(held.started) == 2


async def test_next_job_of_same_task_is_taken_right_away(worker_loop, monkeypatch):
    """Доигравшая job не числится за процессом: следующую job той же задачи берут сразу.

    Иначе разнос захватов ждал бы «молодую» задачу, которой уже нет, а проверка
    дублей сняла бы новый прогон как второй прогон живой задачи.
    """
    monkeypatch.setattr(settings, "WORKER_CLAIM_STAGGER_S", 60)
    held = worker_loop.hold("task.process")
    held.release()  # обработчик отрабатывает сразу

    async with worker_loop.running(slots=2):
        first = await worker_loop.enqueue("task.process", {"task_id": "task-Z"})
        await worker_loop.wait_status(first, "done")
        second = await worker_loop.enqueue("task.process", {"task_id": "task-Z"})
        await worker_loop.wait_status(second, "done")

    assert [p["task_id"] for p in held.started] == ["task-Z", "task-Z"]


async def test_burst_claims_are_stopped_after_first(worker_loop, monkeypatch):
    """Очередь полна, слоты свободны — в работу уходит ОДНА задача, а не все слоты.

    Тот самый дефект: `await sem.acquire()` на свободном слоте не отдаёт
    управление циклу, поэтому пока задача помечалась занятой внутри созданной
    корутины, следующий claim успевал пройти раньше — и три задачи уходили в
    работу за секунды, ни разу не показавшись ни тормозу, ни разносу.
    """
    monkeypatch.setattr(settings, "WORKER_CLAIM_STAGGER_S", 60)
    held = worker_loop.hold("task.process")
    for task_id in ("A", "B", "C", "D"):
        await worker_loop.enqueue("task.process", {"task_id": task_id})

    async with worker_loop.running(slots=4):
        await held.wait_started(1)
        await asyncio.sleep(0.2)  # два десятка опросов очереди — успело бы взять остальные
        assert sorted((await worker_loop.statuses()).values()) == [
            "queued", "queued", "queued", "running",
        ]
        assert len(held.started) == 1


# ---------------------------------------------------------------------------
# Число слотов: потолок — настройка, физика — память и процессор
# ---------------------------------------------------------------------------

def _slots_case(id, *, configured, expected, cores=8, task_mem=400, ratio=0.8,
                min_free=512, **memory):
    return pytest.param(
        dict(configured=configured, cores=cores, task_mem=task_mem, ratio=ratio,
             min_free=min_free, memory=memory),
        expected,
        id=id,
    )


SLOTS_CASES = [
    # Общая машина без личного лимита (прод 30.07.2026): слоты от СВОБОДНОГО, а не
    # от её общего размера. (2500 − 512) / 400 = 4, но настроено 3 — значит 3.
    _slots_case("shared-host-capped-by-setting", configured=3, expected=3,
                rss=200.0, limit=3911.8, source="host", available=2500.0),
    # (1200 − 512) / 400 = 1.
    _slots_case("shared-host-tight", configured=4, expected=1,
                rss=200.0, limit=3911.8, source="host", available=1200.0),
    # Лимит 2 ГБ, занято 800 МБ прайсом: (2048×0.8 − 800) / 400 = 2 — четыре = OOM-kill.
    _slots_case("small-container-limit", configured=4, expected=2,
                rss=800.0, usage=800.0, limit=2048.0),
    # Памяти в обрез — один слот остаётся, иначе очередь не движется.
    _slots_case("never-below-one", configured=4, expected=1,
                rss=980.0, usage=980.0, limit=1024.0),
    _slots_case("plenty-of-memory", configured=4, expected=4,
                rss=500.0, usage=500.0, limit=8192.0),
    # Доля 0 = механизм памяти выключен, а не «оставить один слот».
    _slots_case("ratio-zero-disables", configured=4, expected=4, ratio=0,
                rss=2000.0, usage=2000.0, limit=2048.0),
    # Локально лимита не видно — ведём себя как раньше, ничего не выдумываем.
    _slots_case("no-cgroup", configured=3, expected=3, rss=500.0),
    # Настроено 4, ядер 2 → одно ядро остаётся web: иначе интерфейс не отвечает.
    _slots_case("fewer-cores-than-setting", configured=4, expected=1, cores=2, rss=200.0),
    _slots_case("cores-unknown", configured=3, expected=3, cores=None, rss=200.0),
]


@pytest.mark.parametrize("case, expected", SLOTS_CASES)
async def test_effective_slots(monkeypatch, case, expected):
    monkeypatch.setattr(settings, "WORKER_CONCURRENCY", case["configured"])
    monkeypatch.setattr(settings, "WORKER_TASK_MEM_MB", case["task_mem"])
    monkeypatch.setattr(settings, "WORKER_MEM_HIGH_RATIO", case["ratio"])
    monkeypatch.setattr(settings, "WORKER_MEM_MIN_FREE_MB", case["min_free"])
    monkeypatch.setattr(worker.os, "cpu_count", lambda: case["cores"])
    _snap(monkeypatch, **case["memory"])

    assert worker._effective_slots() == expected
