"""
Кеширование цены не должно перезагружать весь прайс.

Найдено ревью 2026-07-30: `save_to_cache` порождала фоновую задачу, внутри
которой стоял `load_cache(db)` — 4 полных SELECT без лимита (прайс работ, прайс
материалов, два кеша) плюс пересборка numpy-матриц эмбеддингов. Вызывается это на
КАЖДУЮ закешированную позицию, поэтому смета на 458 позиций давала до 458 полных
перезагрузок прайса.

Терять нечего: вектор новой записи нужен лишь семантическому поиску и
подхватится при следующей штатной загрузке кеша.

План: plans/2026-07-30-ispravlenie-nahodok-code-review.md, Фазы 3 и 5.
"""
from contextlib import contextmanager

from sqlalchemy import event, select

from app.models.price_cache import PriceCacheWork
from app.services import price_service
from tests.conftest import test_engine
from tests.helpers.prices import axis, drain_background_embeddings

PRICE_TABLES = ("price_works", "price_materials", "price_cache_works", "price_cache_materials")


@contextmanager
def _sql_log():
    """Все запросы к тестовой БД за время блока (их тексты)."""
    statements: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(test_engine.sync_engine, "before_cursor_execute", _record)
    try:
        yield statements
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", _record)


def _full_reads(statements: list[str]) -> list[str]:
    """SELECT по таблице прайса или кеша без условия — то есть чтение таблицы целиком."""
    found = []
    for statement in statements:
        text = " ".join(statement.split()).lower()
        if not text.startswith("select") or " where " in text:
            continue
        if any(f"from {table}" in text for table in PRICE_TABLES):
            found.append(text)
    return found


async def test_embedding_task_does_not_reload_whole_cache(db_session, app_sessions, price_db):
    """Фоновая задача сохраняет вектор в строку кеша, но прайс целиком не читает."""
    price_db.work("Кладка стен", unit="м3", prices={"Подрядчик": 5000.0}, vector=axis(1))
    price_db.material("Кирпич М150", unit="шт", price=12.5, vector=axis(2))
    await price_db.load()
    price_db.knows("Устройство стяжки", axis(0))

    with _sql_log() as statements:
        await price_service.save_to_cache(
            db_session, "work", "Устройство стяжки", "м2", 350.0, "источник",
        )
        await drain_background_embeddings()

    db_session.expire_all()
    row = (await db_session.execute(
        select(PriceCacheWork).where(PriceCacheWork.name == "Устройство стяжки")
    )).scalar_one()
    assert row.price == 350.0
    assert row.embedding == axis(0), "вектор должен быть сохранён"
    assert _full_reads(statements) == [], "прайс и кеш перечитаны целиком"
