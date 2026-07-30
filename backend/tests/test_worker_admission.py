"""Приём задач: по реальной памяти контейнера и с разносом захватов.

Почему это появилось: 30.07.2026 три возобновлённые задачи захватывались за 2–4
секунды (опрос очереди раз в 2 с), тормоз по памяти смотрел на ТЕКУЩУЮ занятость —
а она в первые секунды ещё низкая — и не срабатывал ни разу. Контейнер получал
OOM-kill. Лечится двумя вещами: доля от реального лимита (cgroup) вместо константы
в мегабайтах и пауза между захватами.

План: plans/2026-07-30-parallelnaya-obrabotka-umiraet.md, Фаза 3.
"""
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
    """Занято 85% лимита контейнера — новую задачу не берём."""
    monkeypatch.setattr(settings, "WORKER_MEM_HIGH_RATIO", 0.8)
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


async def test_ratio_uses_container_not_process(monkeypatch):
    """Считаем занятость контейнера: OOM-killer смотрит на сумму процессов.

    RSS воркера тут скромный, но onnxruntime и прочие дочерние процессы уже съели
    лимит — брать новую задачу нельзя.
    """
    monkeypatch.setattr(settings, "WORKER_MEM_HIGH_RATIO", 0.8)
    monkeypatch.setattr(settings, "WORKER_RSS_PAUSE_MB", 0)
    monkeypatch.setattr(worker, "_inflight_job_ids", {1})
    _snap(monkeypatch, rss=300.0, usage=1900.0, limit=2048.0)

    assert worker._memory_brake_engaged() is True


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


async def test_slots_from_available_memory_on_shared_host(monkeypatch):
    """Слоты на общей машине считаются от свободного, а не от её общего размера.

    (2500 − 512) / 400 = 4 → но настроено 3, значит 3.
    """
    monkeypatch.setattr(settings, "WORKER_CONCURRENCY", 3)
    monkeypatch.setattr(settings, "WORKER_TASK_MEM_MB", 400)
    monkeypatch.setattr(settings, "WORKER_MEM_MIN_FREE_MB", 512)
    _snap(monkeypatch, rss=200.0, limit=3911.8, source="host", available=2500.0)

    assert worker._effective_slots() == 3


async def test_slots_shrink_when_shared_host_is_tight(monkeypatch):
    """Мало свободного на машине — меньше слотов: (1200 − 512) / 400 = 1."""
    monkeypatch.setattr(settings, "WORKER_CONCURRENCY", 4)
    monkeypatch.setattr(settings, "WORKER_TASK_MEM_MB", 400)
    monkeypatch.setattr(settings, "WORKER_MEM_MIN_FREE_MB", 512)
    _snap(monkeypatch, rss=200.0, limit=3911.8, source="host", available=1200.0)

    assert worker._effective_slots() == 1


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


async def test_poll_loop_skips_claim_when_staggered(monkeypatch):
    """Под разносом claim не вызывается, слот возвращается, задачи ждут в очереди."""
    import asyncio

    monkeypatch.setattr(worker, "_memory_brake_engaged", lambda: False)
    monkeypatch.setattr(worker, "_claim_stagger_blocked", lambda: True)

    claims = []

    async def fake_claim(db, worker_id):  # pragma: no cover — не должен вызваться
        claims.append(worker_id)
        return None

    monkeypatch.setattr(worker.job_queue, "claim_one", fake_claim)
    monkeypatch.setattr(settings, "JOB_POLL_INTERVAL_S", 0.01)

    shutdown = asyncio.Event()
    monkeypatch.setattr(worker, "_shutdown", shutdown)

    sem = asyncio.Semaphore(2)
    loop_task = asyncio.create_task(worker._poll_loop(sem, set()))
    await asyncio.sleep(0.05)
    shutdown.set()
    await asyncio.wait_for(loop_task, timeout=2)

    assert claims == []
    assert sem._value == 2


async def test_started_at_recorded_and_cleaned(monkeypatch):
    """Время старта job пишется при захвате и убирается по завершении.

    Иначе разнос захватов либо не сработает, либо запрёт очередь навсегда.
    """
    import asyncio

    from app.models.job import Job

    job = Job(id=77, kind="task.process", payload={}, status="running", attempts=1)
    seen: dict = {}

    async def fake_claim(db, worker_id):
        if job.id in worker._inflight_job_ids or seen.get("claimed"):
            return None
        seen["claimed"] = True
        return job

    async def fake_run(j):
        seen["during"] = dict(worker._inflight_started_at)

    monkeypatch.setattr(worker, "_memory_brake_engaged", lambda: False)
    monkeypatch.setattr(worker, "_claim_stagger_blocked", lambda: False)
    monkeypatch.setattr(worker.job_queue, "claim_one", fake_claim)
    monkeypatch.setattr(worker, "run_job", fake_run)
    monkeypatch.setattr(worker, "_inflight_started_at", {})
    monkeypatch.setattr(worker, "_inflight_job_ids", set())
    monkeypatch.setattr(settings, "JOB_POLL_INTERVAL_S", 0.01)

    shutdown = asyncio.Event()
    monkeypatch.setattr(worker, "_shutdown", shutdown)

    inflight: set = set()
    loop_task = asyncio.create_task(worker._poll_loop(asyncio.Semaphore(2), inflight))
    await asyncio.sleep(0.05)
    shutdown.set()
    await asyncio.wait_for(loop_task, timeout=2)
    await asyncio.gather(*list(inflight), return_exceptions=True)

    assert 77 in seen["during"]
    assert worker._inflight_started_at == {}


# ---------------------------------------------------------------------------
# Число слотов из лимита контейнера
# ---------------------------------------------------------------------------

async def test_slots_limited_by_container_memory(monkeypatch):
    """Маленький пресет — меньше слотов, чем настроено: четыре = OOM-kill.

    Лимит 2 ГБ, занято 800 МБ прайсом, на задачу закладываем 400 МБ:
    (2048×0.8 − 800) / 400 = 2 слота.
    """
    monkeypatch.setattr(settings, "WORKER_CONCURRENCY", 4)
    monkeypatch.setattr(settings, "WORKER_TASK_MEM_MB", 400)
    monkeypatch.setattr(settings, "WORKER_MEM_HIGH_RATIO", 0.8)
    _snap(monkeypatch, rss=800.0, usage=800.0, limit=2048.0)

    assert worker._effective_slots() == 2


async def test_slots_never_below_one(monkeypatch):
    """Даже когда памяти в обрез — один слот остаётся, иначе очередь не движется."""
    monkeypatch.setattr(settings, "WORKER_CONCURRENCY", 4)
    monkeypatch.setattr(settings, "WORKER_TASK_MEM_MB", 400)
    _snap(monkeypatch, rss=980.0, usage=980.0, limit=1024.0)

    assert worker._effective_slots() == 1


async def test_slots_keep_configured_when_memory_is_plenty(monkeypatch):
    monkeypatch.setattr(settings, "WORKER_CONCURRENCY", 4)
    monkeypatch.setattr(settings, "WORKER_TASK_MEM_MB", 400)
    _snap(monkeypatch, rss=500.0, usage=500.0, limit=8192.0)

    assert worker._effective_slots() == 4


async def test_slots_unchanged_when_ratio_disabled(monkeypatch):
    """Доля 0 = механизм памяти выключен, а не «оставить один слот»."""
    monkeypatch.setattr(settings, "WORKER_CONCURRENCY", 4)
    monkeypatch.setattr(settings, "WORKER_TASK_MEM_MB", 400)
    monkeypatch.setattr(settings, "WORKER_MEM_HIGH_RATIO", 0)
    _snap(monkeypatch, rss=2000.0, usage=2000.0, limit=2048.0)

    assert worker._effective_slots() == 4


async def test_burst_claims_are_stopped_after_first(monkeypatch):
    """Очередь полна — за один проход берётся ОДНА задача, а не все слоты.

    Тот самый дефект: `await sem.acquire()` на свободном слоте не отдаёт
    управление циклу, поэтому пока задача помечалась занятой внутри созданной
    корутины, следующий claim успевал пройти раньше — и три задачи уходили в
    работу за секунды, ни разу не показавшись ни тормозу, ни разносу.
    """
    import asyncio

    from app.models.job import Job

    monkeypatch.setattr(settings, "WORKER_CLAIM_STAGGER_S", 60)
    monkeypatch.setattr(settings, "WORKER_MEM_HIGH_RATIO", 0)
    monkeypatch.setattr(settings, "WORKER_RSS_PAUSE_MB", 0)
    monkeypatch.setattr(settings, "JOB_POLL_INTERVAL_S", 0.01)
    monkeypatch.setattr(worker, "_inflight_job_ids", set())
    monkeypatch.setattr(worker, "_inflight_started_at", {})

    counter = {"n": 0}

    async def endless_queue(db, worker_id):
        counter["n"] += 1
        return Job(id=counter["n"], kind="task.process", payload={}, status="running", attempts=1)

    started = asyncio.Event()

    async def slow_run(j):
        started.set()
        await asyncio.sleep(5)  # задача «считается» — слот занят

    monkeypatch.setattr(worker.job_queue, "claim_one", endless_queue)
    monkeypatch.setattr(worker, "run_job", slow_run)

    shutdown = asyncio.Event()
    monkeypatch.setattr(worker, "_shutdown", shutdown)

    inflight: set = set()
    loop_task = asyncio.create_task(worker._poll_loop(asyncio.Semaphore(4), inflight))
    await asyncio.wait_for(started.wait(), timeout=2)
    await asyncio.sleep(0.1)  # успело бы захватить остальные слоты
    shutdown.set()
    await asyncio.wait_for(loop_task, timeout=2)
    for t in inflight:
        t.cancel()
    await asyncio.gather(*list(inflight), return_exceptions=True)

    assert counter["n"] == 1, "взяли больше одной задачи, разнос захватов не работает"


async def test_slots_unchanged_without_cgroup(monkeypatch):
    """Локально лимита не видно — ведём себя как раньше, ничего не выдумываем."""
    monkeypatch.setattr(settings, "WORKER_CONCURRENCY", 3)
    _snap(monkeypatch, rss=500.0, usage=None, limit=None)

    assert worker._effective_slots() == 3
