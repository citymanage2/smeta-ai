"""Тормоз по памяти: адаптивная параллельность вместо жёсткого числа слотов.

Жёсткое `WORKER_CONCURRENCY` не знает, что берёт: четыре тяжёлые сметы валят
процесс, четыре лёгких — нет. Тормоз держит новую задачу в очереди, пока память
выше порога и хоть одна задача уже считается.
"""
import pytest

from app import worker
from app.config import settings
from app.utils.memory import MemorySnapshot

pytestmark = pytest.mark.asyncio


def _rss(monkeypatch, value):
    """Подменить измерение памяти: цифра процесса есть, лимита контейнера нет.

    Именно так выглядит платформа без cgroup — и это тот случай, для которого
    порог `WORKER_RSS_PAUSE_MB` и остался вторым предохранителем. Долю от лимита
    проверяет tests/test_worker_admission.py.
    """
    monkeypatch.setattr(
        worker, "memory_snapshot",
        lambda: MemorySnapshot(rss_mb=value, usage_mb=None, limit_mb=None),
    )


async def test_brake_off_when_disabled(monkeypatch):
    """Порог 0 — тормоз выключен, поведение как раньше."""
    monkeypatch.setattr(settings, "WORKER_RSS_PAUSE_MB", 0)
    _rss(monkeypatch, 99999.0)
    monkeypatch.setattr(worker, "_inflight_job_ids", {1})

    assert worker._memory_brake_engaged() is False


async def test_brake_off_below_limit(monkeypatch):
    """Память в норме — берём задачи как обычно."""
    monkeypatch.setattr(settings, "WORKER_RSS_PAUSE_MB", 1536)
    _rss(monkeypatch, 400.0)
    monkeypatch.setattr(worker, "_inflight_job_ids", {1})

    assert worker._memory_brake_engaged() is False


async def test_brake_off_when_rss_unknown(monkeypatch):
    """Платформа не дала цифру → не тормозим (иначе встанет вся очередь)."""
    monkeypatch.setattr(settings, "WORKER_RSS_PAUSE_MB", 1536)
    _rss(monkeypatch, None)
    monkeypatch.setattr(worker, "_inflight_job_ids", {1})

    assert worker._memory_brake_engaged() is False
