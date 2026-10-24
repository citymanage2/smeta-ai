"""Настоящий цикл воркера на тестовой БД: очередь, захват, запуск, статусы job.

Зачем. Тесты воркера подменяли `claim_one`, `run_job` и приватные множества
`_inflight_*`, а проверяли список вызовов подделок и `sem._value`. Так нельзя
поймать то, ради чего эти правила писались: что job осталась в очереди, что дубль
снят, что задача не ушла в работу дважды. Здесь `_poll_loop` крутится по-
настоящему: job лежат в таблице `jobs`, захватывает их `job_queue.claim_one`,
исполняет `run_job`, а тест смотрит на статус job в БД. Подменён только внешний
мир: число ядер (`os.cpu_count`) и память процесса (`memory_snapshot`, `rss_mb`).

Почему база своя, а не общая `TestSessionLocal`. Общая in-memory база — одно
соединение на все сессии, и `rollback()` любой из них откатывает чужую
незакоммиченную запись. У воркера сессии конкурируют по-настоящему: захват на
пустой очереди делает `rollback()`, и `complete` доигравшей рядом job молча
терялся — job навсегда оставалась `running`. Поэтому у цикла своя база на
файле, по соединению на сессию, как у Postgres в проде (тот же приём, что в
`test_chunks_watcher_session.py`). Фабрика её сессий — `worker_loop.sessions`;
`app.database.AsyncSessionLocal` и `worker.AsyncSessionLocal` смотрят туда же.

Как пользоваться (фикстура `worker_loop`):

    async def test_...(worker_loop):
        held = worker_loop.hold("test.slow")            # обработчик держит job
        first = await worker_loop.enqueue("test.slow", {"task_id": "A"})
        async with worker_loop.running(slots=2):        # цикл воркера в фоне
            await held.wait_started(1)
            assert await worker_loop.status(first) == "running"
            held.release()
            await worker_loop.wait_status(first, "done")

* Обработчик: `worker_loop.handle(kind, async fn(payload, db))` или
  `worker_loop.hold(kind)` — держит каждую job, пока не `release()`;
  `held.started` — payload запущенных job (по нему видно, что запускалось).
* Очередь: `enqueue(kind, payload)` → id job; `status(id)`, `statuses()` —
  из БД свежей сессией; `wait_status(id, *статусы)` — дождаться (2 с).
* Внешний мир по умолчанию «спокойный»: 4 ядра, память не тесная, разнос
  захватов выключен (`WORKER_CLAIM_STAGGER_S=0`), опрос очереди — 10 мс.
  Меняется явно: `worker_loop.cores(2)`, `worker_loop.memory(usage=1900,
  limit=2048)`, `monkeypatch.setattr(settings, "WORKER_CLAIM_STAGGER_S", 60)`.
* База — своя на каждый тест (все таблицы, пустые); состояние процесса
  воркера (`_shutdown`, `_inflight_*`) — тоже своё. Строки, которые нужны
  обработчику (задачи и т. п.), заводятся через `worker_loop.sessions()`.
"""
import asyncio
import contextlib
from typing import Any, Awaitable, Callable, Optional

import pytest_asyncio
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.job import Job
from app.utils.memory import MemorySnapshot

# Память «не тесная»: лимита нет, процесс маленький — тормоз не срабатывает.
CALM_MEMORY = MemorySnapshot(rss_mb=200.0, usage_mb=None, limit_mb=None)

Handler = Callable[[dict, Any], Awaitable[None]]


class HeldJobs:
    """Обработчик, который держит каждую job «в работе», пока тест не отпустит."""

    def __init__(self) -> None:
        self.started: list[dict] = []
        self._released = asyncio.Event()
        self._changed = asyncio.Event()

    async def __call__(self, payload: dict, db) -> None:
        self.started.append(payload)
        self._changed.set()
        await self._released.wait()

    def release(self) -> None:
        self._released.set()

    async def wait_started(self, count: int = 1, timeout: float = 2.0) -> None:
        async def _until() -> None:
            while len(self.started) < count:
                self._changed.clear()
                await self._changed.wait()

        await asyncio.wait_for(_until(), timeout)


class WorkerLoop:
    def __init__(self, monkeypatch, session_factory) -> None:
        from app import worker
        from app.config import settings

        import app.database as db_module

        self._worker = worker
        self._monkeypatch = monkeypatch
        self.sessions = session_factory
        self._held: list[HeldJobs] = []
        monkeypatch.setattr(db_module, "AsyncSessionLocal", session_factory)
        monkeypatch.setattr(worker, "AsyncSessionLocal", session_factory)
        monkeypatch.setattr(worker, "_shutdown", asyncio.Event())
        monkeypatch.setattr(worker, "_inflight_job_ids", set())
        monkeypatch.setattr(worker, "_inflight_started_at", {})
        monkeypatch.setattr(worker, "_inflight_task_ids", {})
        monkeypatch.setattr(settings, "JOB_POLL_INTERVAL_S", 0.01)
        monkeypatch.setattr(settings, "WORKER_CLAIM_STAGGER_S", 0)
        self.cores(4)
        self.memory()

    # ── внешний мир ──────────────────────────────────────────────────────
    def cores(self, count: Optional[int]) -> None:
        """Сколько ядер «у машины» (None — платформа не сказала)."""
        self._monkeypatch.setattr(self._worker.os, "cpu_count", lambda: count)

    def memory(
        self,
        *,
        rss: Optional[float] = 200.0,
        usage: Optional[float] = None,
        limit: Optional[float] = None,
        source: Optional[str] = None,
        available: Optional[float] = None,
    ) -> None:
        """Что покажет измерение памяти. `limit` без `source` — личный лимит контейнера."""
        if source is None and limit is not None:
            source = "cgroup"
        snap = MemorySnapshot(rss_mb=rss, usage_mb=usage, limit_mb=limit,
                              limit_source=source, available_mb=available)
        self._monkeypatch.setattr(self._worker, "memory_snapshot", lambda: snap)
        self._monkeypatch.setattr(self._worker, "rss_mb", lambda: rss)

    # ── обработчики ──────────────────────────────────────────────────────
    def handle(self, kind: str, handler: Handler) -> None:
        self._monkeypatch.setitem(self._worker.HANDLERS, kind, handler)

    def hold(self, kind: str) -> HeldJobs:
        held = HeldJobs()
        self._held.append(held)
        self.handle(kind, held)
        return held

    # ── очередь ──────────────────────────────────────────────────────────
    async def enqueue(self, kind: str, payload: Optional[dict] = None, **kwargs: Any) -> int:
        from app.services import job_queue

        async with self.sessions() as db:
            job = await job_queue.enqueue(db, kind, payload or {}, **kwargs)
            return job.id

    async def status(self, job_id: int) -> Optional[str]:
        async with self.sessions() as db:
            return (await db.execute(select(Job.status).where(Job.id == job_id))).scalar_one_or_none()

    async def statuses(self) -> dict[int, str]:
        async with self.sessions() as db:
            return dict((await db.execute(select(Job.id, Job.status))).all())

    async def wait_status(self, job_id: int, *expected: str, timeout: float = 2.0) -> str:
        async def _until() -> str:
            while True:
                current = await self.status(job_id)
                if current in expected:
                    return current
                await asyncio.sleep(0.01)

        try:
            return await asyncio.wait_for(_until(), timeout)
        except asyncio.TimeoutError:
            raise AssertionError(
                f"job {job_id}: ждали {expected}, а она {await self.status(job_id)!r}"
            ) from None

    # ── цикл ─────────────────────────────────────────────────────────────
    @contextlib.asynccontextmanager
    async def running(self, slots: int = 2):
        """Крутить `_poll_loop` в фоне; на выходе — штатная остановка и дренаж."""
        worker = self._worker
        inflight: set = set()
        loop_task = asyncio.create_task(worker._poll_loop(asyncio.Semaphore(slots), inflight))
        try:
            yield
        finally:
            # Сначала отпустить удержанные job: снимать `cancel()` корутину посреди
            # запроса к БД нельзя (правило №23), пусть доиграют сами.
            for held in self._held:
                held.release()
            worker._shutdown.set()
            await asyncio.wait_for(loop_task, timeout=5)
            if inflight:
                _, pending = await asyncio.wait(list(inflight), timeout=2)
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)


@pytest_asyncio.fixture
async def worker_loop(monkeypatch, tmp_path):
    """Цикл воркера на своей тестовой БД; описание — в модуле."""
    from tests.conftest import _register_sqlite_functions

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'worker.sqlite'}")
    event.listen(engine.sync_engine, "connect", _register_sqlite_functions)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    loop = WorkerLoop(monkeypatch, async_sessionmaker(engine, expire_on_commit=False))
    yield loop
    await engine.dispose()
