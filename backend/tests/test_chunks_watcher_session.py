"""
Сессия БД задачи переживает параллельную пачку чанков.

Инцидент 20.10.2026: смета упала на «Расчёт цен: посчитано 16 из 26 частей» с
`PendingRollbackError: Can't reconnect until invalid transaction is rolled back`.

Механика. Пока чанки считаются, `self.db` трогает только watcher (проверка отмены
и строка «готово N из M»). Пачка кончалась — и watcher снимали `cancel()`, даже
если он был посреди запроса. SQLAlchemy считает прерванный запрос оборванным
соединением и помечает его негодным внутри открытой транзакции. Дальше каждая
запись в кеш цен молча падала (`_cache_priced_item` глотает ошибки), а первая
запись прогресса роняла задачу — и оплаченные ответы ИИ этой группы так и не
попадали в чекпоинт.

План: plans/2026-10-20-sessiya-bd-posle-pachki-chankov.md.
"""
import asyncio
import sys
import time
import uuid
from unittest.mock import MagicMock

import pytest_asyncio
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# fitz (PyMuPDF) может отсутствовать в тестовом окружении — мок до импорта task_processor
sys.modules.setdefault("fitz", MagicMock())

from app.database import Base
from app.models.task import Task
from app.services import task_processor as tp
from app.services.task_processor import TaskProcessor

SLOW_QUERY_S = 0.3


def _sleep_then_one() -> int:
    time.sleep(SLOW_QUERY_S)
    return 1


@pytest_asyncio.fixture
async def session_factory(tmp_path):
    """Своя БД на файле: соединение здесь рвётся по-настоящему, и новое должно
    видеть те же таблицы (у общей in-memory базы после обрыва их бы не было)."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'watcher.sqlite'}")

    @event.listens_for(engine.sync_engine, "connect")
    def _register_slow(dbapi_conn, _record):
        # Функция выполняется в потоке драйвера — честный «долгий запрос».
        dbapi_conn.run_async(lambda c: c.create_function("slow", 0, _sleep_then_one))

    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=[Task.__table__]))
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _drop_connection(db) -> None:
    """Обрыв соединения посреди транзакции — как падение сети до managed-PG."""
    conn = await db.connection()
    await conn.invalidate()
    raise OperationalError("select 1", {}, Exception("connection was closed in the middle of operation"))


async def test_watcher_is_not_cancelled_in_the_middle_of_a_query(session_factory):
    async with session_factory() as db:
        p = TaskProcessor("tid-race", db=db)

        async def slow_check():
            await db.execute(text("select slow()"))

        p._check_cancelled = slow_check

        async def chunk():
            # Пачка кончается, пока watcher внутри запроса.
            await asyncio.sleep(0.15)
            return "ok"

        results = await p._run_chunks_parallel(
            [chunk], cancel_check_interval=0.05, return_exceptions=True
        )

        assert results == ["ok"]
        # Основная корутина продолжает на той же сессии — как запись прогресса
        # после пачки. Раньше здесь был PendingRollbackError.
        assert (await db.execute(text("select 1"))).scalar() == 1


async def test_failed_cancel_check_heals_session_and_watcher_keeps_watching(session_factory):
    async with session_factory() as db:
        p = TaskProcessor("tid-drop", db=db)
        calls = {"n": 0}

        async def flaky_check():
            calls["n"] += 1
            if calls["n"] == 1:
                await _drop_connection(db)
            await db.execute(text("select 1"))

        p._check_cancelled = flaky_check

        async def chunk():
            await asyncio.sleep(0.4)
            return "ok"

        results = await p._run_chunks_parallel(
            [chunk], cancel_check_interval=0.05, return_exceptions=True
        )

        assert results == ["ok"]
        # Раньше сбой проверки молча убивал watcher: до конца пачки — ни отмены,
        # ни дедлайна, ни строки прогресса.
        assert calls["n"] >= 2
        assert (await db.execute(text("select 1"))).scalar() == 1


async def test_failed_progress_write_heals_session_before_cancel_check(session_factory):
    async with session_factory() as db:
        p = TaskProcessor("tid-progress", db=db)
        checks = {"ok": 0}

        async def broken_progress(_message):
            await _drop_connection(db)

        async def check():
            await db.execute(text("select 1"))
            checks["ok"] += 1

        p.update_progress_message = broken_progress
        p._check_cancelled = check

        async def chunk():
            await asyncio.sleep(0.3)
            return "ok"

        results = await p._run_chunks_parallel(
            [chunk],
            cancel_check_interval=0.05,
            return_exceptions=True,
            progress_label="Расчёт цен: готово {done} из {total} частей...",
        )

        assert results == ["ok"]
        assert checks["ok"] >= 1
        assert (await db.execute(text("select 1"))).scalar() == 1


async def test_failed_cache_write_does_not_break_the_next_progress_write(
    session_factory, monkeypatch
):
    async with session_factory() as db:
        task = Task(
            id=str(uuid.uuid4()),
            user_role="manager",
            task_type="ESTIMATE_FROM_LIST",
            status="processing",
        )
        db.add(task)
        await db.commit()
        p = TaskProcessor(task.id, db=db)

        async def broken_save(session, *_args, **_kwargs):
            await _drop_connection(session)

        monkeypatch.setattr(tp._price_svc, "save_to_cache", broken_save)

        await p._cache_priced_item(
            {"id": 1, "type": "Работа", "name": "Монтаж перегородки", "unit": "м2", "work_price": 1200}
        )

        # Объект задачи, загруженный до сбоя, читается сразу: откат помечает его
        # устаревшим, и без перечитывания async-код упал бы на ленивой загрузке.
        assert task.status == "processing"

        # То, что роняло задачу: первая запись прогресса после сбоя кеша.
        await p.update_progress("Расчёт цен: посчитано 1 из 2 частей, осталось 1.")

    async with session_factory() as check_db:
        saved = await check_db.get(Task, task.id)
        assert saved.progress_message == "Расчёт цен: посчитано 1 из 2 частей, осталось 1."
