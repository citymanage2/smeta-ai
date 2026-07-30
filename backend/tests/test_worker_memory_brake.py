"""Тормоз по памяти: адаптивная параллельность вместо жёсткого числа слотов.

Жёсткое `WORKER_CONCURRENCY` не знает, что берёт: четыре тяжёлые сметы валят
процесс, четыре лёгких — нет. Тормоз держит новую задачу в очереди, пока память
выше порога и хоть одна задача уже считается.
"""
import pytest

from app import worker
from app.config import settings

pytestmark = pytest.mark.asyncio


async def test_brake_off_when_disabled(monkeypatch):
    """Порог 0 — тормоз выключен, поведение как раньше."""
    monkeypatch.setattr(settings, "WORKER_RSS_PAUSE_MB", 0)
    monkeypatch.setattr(worker, "rss_mb", lambda: 99999.0)
    monkeypatch.setattr(worker, "_inflight_job_ids", {1})

    assert worker._memory_brake_engaged() is False


async def test_brake_off_when_idle(monkeypatch):
    """Пустой процесс не тормозим никогда.

    Иначе высокая база (загруженный прайс, матрицы эмбеддингов) заперла бы
    очередь навсегда: брать нечего, а память сама не упадёт.
    """
    monkeypatch.setattr(settings, "WORKER_RSS_PAUSE_MB", 500)
    monkeypatch.setattr(worker, "rss_mb", lambda: 99999.0)
    monkeypatch.setattr(worker, "_inflight_job_ids", set())

    assert worker._memory_brake_engaged() is False


async def test_brake_off_below_limit(monkeypatch):
    """Память в норме — берём задачи как обычно."""
    monkeypatch.setattr(settings, "WORKER_RSS_PAUSE_MB", 1536)
    monkeypatch.setattr(worker, "rss_mb", lambda: 400.0)
    monkeypatch.setattr(worker, "_inflight_job_ids", {1})

    assert worker._memory_brake_engaged() is False


async def test_brake_on_above_limit_while_busy(monkeypatch):
    """Память выше порога и задача в работе — новую не берём."""
    monkeypatch.setattr(settings, "WORKER_RSS_PAUSE_MB", 1536)
    monkeypatch.setattr(worker, "rss_mb", lambda: 1600.0)
    monkeypatch.setattr(worker, "_inflight_job_ids", {1})

    assert worker._memory_brake_engaged() is True


async def test_brake_off_when_rss_unknown(monkeypatch):
    """Платформа не дала цифру → не тормозим (иначе встанет вся очередь)."""
    monkeypatch.setattr(settings, "WORKER_RSS_PAUSE_MB", 1536)
    monkeypatch.setattr(worker, "rss_mb", lambda: None)
    monkeypatch.setattr(worker, "_inflight_job_ids", {1})

    assert worker._memory_brake_engaged() is False


async def test_pause_threshold_above_warn():
    """Тормоз должен срабатывать позже предупреждения, иначе жалоба бессмысленна."""
    assert settings.WORKER_RSS_PAUSE_MB > settings.WORKER_RSS_WARN_MB


async def test_poll_loop_skips_claim_when_braked(monkeypatch):
    """Под тормозом claim не вызывается, слот освобождается, задачи не теряются."""
    import asyncio

    monkeypatch.setattr(worker, "_memory_brake_engaged", lambda: True)

    claims = []

    async def fake_claim(db, worker_id):  # pragma: no cover — не должен вызваться
        claims.append(worker_id)
        return None

    monkeypatch.setattr(worker.job_queue, "claim_one", fake_claim)
    monkeypatch.setattr(settings, "JOB_POLL_INTERVAL_S", 0.01)

    # Событие остановки создаём в ЭТОМ цикле: модульное привязано к циклу импорта
    # (Python 3.9), и ожидание из другого цикла падает RuntimeError.
    shutdown = asyncio.Event()
    monkeypatch.setattr(worker, "_shutdown", shutdown)

    sem = asyncio.Semaphore(2)
    loop_task = asyncio.create_task(worker._poll_loop(sem, set()))
    await asyncio.sleep(0.05)
    shutdown.set()
    await asyncio.wait_for(loop_task, timeout=2)

    assert claims == []
    assert sem._value == 2  # слот возвращён, а не утёк
