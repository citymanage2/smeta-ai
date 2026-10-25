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
from tests.helpers.prices import axis, similar

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize(
    "warmup",
    [worker._warm_price_cache, worker._ensure_price_cache],
    ids=["on_start", "scheduled_retry"],
)
async def test_warmup_makes_price_list_searchable(price_db, app_sessions, warmup):
    """После прогрева (на старте или добором по расписанию, если старт не удался)
    позиция сметы находит цену в корпоративном прайсе; до него — нет.

    Ровно это и ломалось: с пустым кэшем поиск по смыслу молча отвечал «не
    найдено», и позиция уходила в ИИ с платным веб-поиском.
    """
    price_db.work("Кладка стен из кирпича", unit="м3", prices={"Подрядчик": 5000}, vector=axis(0))
    price_db.knows("Кладка кирпичных стен", similar(0.95, to=0))
    await price_db.db.commit()
    assert await price_service.batch_embedding_match_works(["Кладка кирпичных стен"]) == [None]

    await warmup()

    assert price_service.is_cache_loaded() is True
    [found] = await price_service.batch_embedding_match_works(["Кладка кирпичных стен"])
    assert found["name"] == "Кладка стен из кирпича"
    assert found["min_price"] == 5000


async def test_warm_price_cache_survives_db_failure(monkeypatch):
    """БД недоступна (первый деплой) → предупреждение, не падение.

    Иначе worker не поднялся бы вовсе и очередь встала целиком.
    """
    async def boom(db):
        raise RuntimeError("db not ready")

    monkeypatch.setattr(price_service, "load_cache", boom)
    await worker._warm_price_cache()  # не должно бросить


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
