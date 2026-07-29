"""Прайс должен быть в памяти обработчика ДО первой задачи.

Регресс 29–30.07.2026: в worker `load_cache` вызывался только внутри суточной
чистки, то есть впервые через 24 часа после старта. Процесс перезапускается на
каждом деплое, поэтому кэш был пуст всегда: поиск цены выходил по
`_works_embeddings is None`, отдавал «не найдено» на все позиции, и каждая шла в
ИИ с платным web-поиском. Смета на 464 позиции считалась часами и без
корпоративных цен.
"""
import pytest

from app import worker
from app.services import price_service

pytestmark = pytest.mark.asyncio


async def test_warm_price_cache_loads(monkeypatch):
    """Прогрев зовёт load_cache — ровно один раз."""
    calls = []

    async def fake_load_cache(db):
        calls.append(db)

    monkeypatch.setattr(price_service, "load_cache", fake_load_cache)
    await worker._warm_price_cache()

    assert len(calls) == 1


async def test_warm_price_cache_survives_db_failure(monkeypatch):
    """БД недоступна (первый деплой) → предупреждение, не падение.

    Иначе worker не поднялся бы вовсе и очередь встала целиком.
    """
    async def boom(db):
        raise RuntimeError("db not ready")

    monkeypatch.setattr(price_service, "load_cache", boom)
    await worker._warm_price_cache()  # не должно бросить


async def test_ensure_price_cache_skips_when_loaded(monkeypatch):
    """Загруженный кэш не перезагружаем — полная перезагрузка бьёт по БД."""
    calls = []

    async def fake_load_cache(db):
        calls.append(db)

    monkeypatch.setattr(price_service, "load_cache", fake_load_cache)
    monkeypatch.setattr(price_service, "is_cache_loaded", lambda: True)
    await worker._ensure_price_cache()

    assert calls == []


async def test_ensure_price_cache_retries_when_empty(monkeypatch):
    """Кэш пуст (прогрев на старте не удался) → дожимаем по расписанию."""
    calls = []

    async def fake_load_cache(db):
        calls.append(db)

    monkeypatch.setattr(price_service, "load_cache", fake_load_cache)
    monkeypatch.setattr(price_service, "is_cache_loaded", lambda: False)
    await worker._ensure_price_cache()

    assert len(calls) == 1


async def test_ensure_price_cache_is_scheduled():
    """Добор прогрева должен стоять в планировщике, иначе неудача старта вечна."""
    scheduler = worker._build_scheduler()  # не запускаем: нужен только состав job
    funcs = {job.func for job in scheduler.get_jobs()}
    assert worker._ensure_price_cache in funcs


async def test_is_cache_loaded_reflects_load(db_session, monkeypatch):
    """Флаг честный: до load_cache — False, после — True."""
    monkeypatch.setattr(price_service, "_cache_loaded", False)
    assert price_service.is_cache_loaded() is False

    await price_service.load_cache(db_session)
    assert price_service.is_cache_loaded() is True
