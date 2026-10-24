"""Задача и `TaskProcessor` на тестовой БД: прогон настоящий, подменён только ИИ.

Зачем. Около сорока тестов обработки строили `TaskProcessor(db=MagicMock())`,
подменяли половину его собственных методов и разбирали `await_args` — то есть
проверяли, как процессор зовёт сам себя. Переписали внутренности, поведение то
же — тесты падают; сломали поведение — проходят. Здесь задача лежит в БД,
процессор работает на `db_session` со всеми своими записями (прогресс, чекпоинты,
журнал вызовов, рабочая версия сметы, файл в S3), а результат читается оттуда же,
откуда его читает пользователь.

Как пользоваться (фикстура `processor_env`; рядом — `claude_api` и `price_db`):

    async def test_...(processor_env, claude_api, price_db):
        price_db.material("Смеси сухие", unit="т", price=73770)   # прайс в БД
        claude_api({"items": [...]})                             # ответы ИИ по порядку
        task = await processor_env.estimate_task([
            {"type": "Материал", "name": "Смеси сухие", "unit": "кг", "quantity": 30},
        ])
        task = await processor_env.run(task)                     # TaskProcessor.process()
        assert task.status == "completed"
        items = await processor_env.estimate_items(task)        # рабочая версия сметы

* Задачи: `await processor_env.task("LIST_FROM_GRAND", status=..., **поля Task)`;
  `estimate_task(items)` — смета из перечня (Path B: перечень-источник с этими
  позициями заводится сам); `input_file(task, name, mime, data)` — входной файл
  в S3 и `task_input_files`.
* Прогон: `await processor_env.run(task)` — `process()` целиком, как в воркере;
  перед ним кеш подбора цен собирается из БД (как прогрев воркера), так что
  строки `price_db` видны. Возвращает задачу, перечитанную из БД.
  `processor_env.processor(task)` — процессор на той же сессии, если тест
  проверяет отдельный шаг (веха прогресса, чекпоинт).
* Результат: `reload(task)` — свежая строка (`status`, `progress_data`,
  `progress_log`, `cost`, `error_message`); `estimate_items(task)` — смета через
  `estimate_store.read_items`; ответы ИИ и их число — `claude_api(...).calls`.
* Подменено: ИИ (`claude_api`/`patch_claude_create`), модель эмбеддингов и
  таблицы цен (`price_db`), S3 (`fake_s3`). Свои сессии приложения
  (`AsyncSessionLocal()`) идут в тестовую БД (`app_sessions`). Задачи фикстуры и
  всё, что к ним записано, удаляются после теста.
"""
import json
import uuid
from typing import Any, Optional

import pytest_asyncio
from sqlalchemy import delete, select

from app.models.ai_baseline import AiBaseline
from app.models.api_call_log import ApiCallLog
from app.models.estimate_version import EstimateVersion
from app.models.history import TaskHistory
from app.models.job import Job
from app.models.result import TaskResult
from app.models.task import Task
from app.models.task_input_file import TaskInputFile
from app.services import estimate_store
from app.services.task_processor import TaskProcessor
from tests.helpers.prices import drain_background_embeddings

# Что пишет обработка задачи (по task_id) — удаляется вместе с задачами фикстуры.
_TASK_ROWS = (TaskResult, TaskInputFile, EstimateVersion, AiBaseline, ApiCallLog, TaskHistory)


def _id(task) -> str:
    """id задачи без обращения к БД: после `expire_all` атрибут объекта уже не прочитать."""
    from sqlalchemy import inspect

    state = inspect(task)
    return str(state.identity[0] if state.identity else task.id)


class ProcessorEnv:
    def __init__(self, db, price_db) -> None:
        self.db = db
        self.price_db = price_db
        self.task_ids: list[str] = []

    # ── задачи ───────────────────────────────────────────────────────────
    async def task(self, task_type: str, *, status: str = "pending", **fields: Any) -> Task:
        """Задача в БД (коммит). Поля по умолчанию — как у задачи из интерфейса."""
        values: dict[str, Any] = dict(
            id=str(uuid.uuid4()), owner_id=1, user_role="project_manager",
            task_type=task_type, status=status,
            input_files=[], input_file_data=[], chat_history=[],
        )
        values.update(fields)
        task = Task(**values)
        self.db.add(task)
        await self.db.commit()
        self.task_ids.append(str(task.id))
        return task

    async def list_task(self, items: list[dict], **fields: Any) -> Task:
        """Посчитанный перечень: его позиции лежат в `progress_data['items']`."""
        fields.setdefault("status", "completed")
        return await self.task("LIST_FROM_GRAND", progress_data={"items": items}, **fields)

    async def estimate_task(
        self, items: list[dict], *, processing_mode: str = "fast", **fields: Any
    ) -> Task:
        """Смета из перечня (Path B): перечень-источник с `items` заводится здесь же."""
        source = await self.list_task(items)
        prompt = json.dumps({"path": "B", "source_task_id": str(source.id), "source_stage": 1})
        return await self.task(
            "ESTIMATE_FROM_LIST", user_prompt=prompt, processing_mode=processing_mode, **fields,
        )

    async def input_file(self, task: Task, name: str, mime: str, data: bytes, index: int = 0):
        """Входной файл задачи: байты в S3, строка в `task_input_files`."""
        from tests.conftest import store_input_row

        row = await store_input_row(self.db, str(task.id), index, name, mime, data)
        await self.db.commit()
        return row

    # ── прогон ───────────────────────────────────────────────────────────
    def processor(self, task: Task, **kwargs: Any) -> TaskProcessor:
        return TaskProcessor(str(task.id), self.db, **kwargs)

    async def run(self, task: Task, **kwargs: Any) -> Task:
        """`TaskProcessor.process()` целиком; вернуть задачу, перечитанную из БД."""
        await self.price_db.load()
        await self.processor(task, **kwargs).process()
        await drain_background_embeddings()
        return await self.reload(task)

    # ── результат ────────────────────────────────────────────────────────
    async def reload(self, task: Task) -> Task:
        """Задача из БД, а не из кеша сессии (`expire_on_commit=False` у тестовой)."""
        task_id = _id(task)
        self.db.expire_all()
        fresh = await self.db.get(Task, task_id)
        assert fresh is not None, "задача пропала из БД"
        return fresh

    async def estimate_items(self, task: Task) -> list[dict]:
        """Смета так, как её читают редактор, xlsx и добор цен: рабочая версия."""
        return await estimate_store.read_items(self.db, await self.reload(task))

    async def results(self, task: Task, slot: Optional[str] = None) -> list[TaskResult]:
        """Файлы результата задачи (по слоту — если задан)."""
        task_id = _id(task)
        self.db.expire_all()
        query = select(TaskResult).where(TaskResult.task_id == task_id)
        if slot is not None:
            query = query.where(TaskResult.slot == slot)
        return list((await self.db.execute(query)).scalars().all())

    async def cleanup(self) -> None:
        if not self.task_ids:
            return
        for model in _TASK_ROWS:
            await self.db.execute(delete(model).where(model.task_id.in_(self.task_ids)))
        jobs = (await self.db.execute(select(Job.id, Job.payload))).all()
        job_ids = [jid for jid, payload in jobs if (payload or {}).get("task_id") in self.task_ids]
        if job_ids:
            await self.db.execute(delete(Job).where(Job.id.in_(job_ids)))
        await self.db.execute(delete(Task).where(Task.id.in_(self.task_ids)))
        await self.db.commit()


@pytest_asyncio.fixture
async def processor_env(db_session, app_sessions, price_db, fake_s3):
    """Задачи и `TaskProcessor` на тестовой БД; описание — в модуле."""
    env = ProcessorEnv(db_session, price_db)
    yield env
    await drain_background_embeddings()
    await db_session.rollback()
    await env.cleanup()
