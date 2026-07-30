"""Расход памяти обработчика должен быть измерен и виден в админке.

До 30.07.2026 память не измерялась вообще: спор «считать 4 задачи параллельно или
1» шёл без единой цифры, хотя именно ресурсы убивали worker. Web память воркера
не видит (другой контейнер), поэтому цифра идёт записью в system_events, а оттуда
в блок «Диагностика».
"""
import pytest
from sqlalchemy import delete, select

from app import worker
from app.config import settings
from app.models.system_event import KIND_WORKER_MEMORY_HIGH, SystemEvent

pytestmark = pytest.mark.asyncio


async def _clear_events(db):
    await db.execute(delete(SystemEvent))
    await db.commit()


async def _events(db) -> list:
    db.expire_all()
    return (
        (
            await db.execute(
                select(SystemEvent.payload).where(SystemEvent.kind == KIND_WORKER_MEMORY_HIGH)
            )
        )
        .scalars()
        .all()
    )


async def test_rss_mb_returns_number():
    """Измерение работает на текущей платформе (Linux — /proc, macOS — resource)."""
    value = worker.rss_mb()
    assert value is None or value > 0


async def test_rss_fields_include_delta():
    """В лог job уходит и текущее значение, и прибавка за задачу."""
    fields = worker._rss_fields(1.0)
    if not fields:  # платформа не дала цифру — измерение необязательно
        pytest.skip("rss недоступен")
    assert "rss_mb" in fields
    assert "rss_delta_mb" in fields


async def test_memory_below_threshold_is_silent(db_session, monkeypatch):
    """Норма не пишется в БД: диагностика не должна сама создавать нагрузку."""
    from tests.conftest import TestSessionLocal

    monkeypatch.setattr(worker, "AsyncSessionLocal", TestSessionLocal)
    monkeypatch.setattr(settings, "WORKER_RSS_WARN_MB", 1024)
    await _clear_events(db_session)

    await worker._report_memory_if_high(100.0)

    assert await _events(db_session) == []


async def test_memory_above_threshold_recorded(db_session, monkeypatch):
    """Превышение порога → запись с цифрой, порогом и числом слотов."""
    from tests.conftest import TestSessionLocal

    monkeypatch.setattr(worker, "AsyncSessionLocal", TestSessionLocal)
    monkeypatch.setattr(settings, "WORKER_RSS_WARN_MB", 500)
    await _clear_events(db_session)

    await worker._report_memory_if_high(1500.5)

    payloads = await _events(db_session)
    assert len(payloads) == 1
    assert payloads[0]["rss_mb"] == 1500.5
    assert payloads[0]["threshold_mb"] == 500
    assert payloads[0]["concurrency"] == settings.WORKER_CONCURRENCY


async def test_memory_report_deduped(db_session, monkeypatch):
    """Вторая жалоба в течение 30 минут не пишется — иначе таблица распухнет."""
    from tests.conftest import TestSessionLocal

    monkeypatch.setattr(worker, "AsyncSessionLocal", TestSessionLocal)
    monkeypatch.setattr(settings, "WORKER_RSS_WARN_MB", 500)
    await _clear_events(db_session)

    await worker._report_memory_if_high(1500.0)
    await worker._report_memory_if_high(1600.0)

    assert len(await _events(db_session)) == 1


async def test_memory_unavailable_is_silent(db_session, monkeypatch):
    """Нет цифры (платформа не дала) → тишина, не падение."""
    from tests.conftest import TestSessionLocal

    monkeypatch.setattr(worker, "AsyncSessionLocal", TestSessionLocal)
    await _clear_events(db_session)

    await worker._report_memory_if_high(None)

    assert await _events(db_session) == []
