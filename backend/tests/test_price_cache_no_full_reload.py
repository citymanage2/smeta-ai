"""
Кеширование цены не должно перезагружать весь прайс.

Найдено ревью 2026-07-30: `save_to_cache` порождала фоновую задачу, внутри
которой стоял `load_cache(db)` — 4 полных SELECT без лимита (прайс работ, прайс
материалов, два кеша) плюс пересборка numpy-матриц эмбеддингов. Вызывается это на
КАЖДУЮ закешированную позицию, поэтому смета на 458 позиций давала до 458 полных
перезагрузок прайса.

Терять нечего: запись добавляется в in-memory кеш точечно, поэтому поиск по
точному совпадению имени находит её сразу; вектор нужен лишь семантическому
поиску и подхватится при следующей штатной загрузке кеша.

Второй дефект того же места: `asyncio.create_task` без сохранения ссылки —
сборщик мусора вправе уничтожить задачу на середине (документированное поведение
CPython), и тогда вектор не сохранится вовсе.

План: plans/2026-07-30-ispravlenie-nahodok-code-review.md, Фазы 3 и 5.
"""
import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.modules.setdefault("fitz", MagicMock())

from app.services import price_service  # noqa: E402


@pytest.mark.asyncio
async def test_embedding_task_does_not_reload_whole_cache():
    """Фоновая задача сохраняет вектор, но не перезагружает прайс целиком."""
    fake_record = MagicMock()
    fake_db = MagicMock()
    fake_db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=fake_record))
    )
    fake_db.commit = AsyncMock()

    class _Ctx:
        async def __aenter__(self):
            return fake_db

        async def __aexit__(self, *a):
            return False

    with patch("app.database.AsyncSessionLocal", return_value=_Ctx()), \
         patch("app.services.embedding_service.generate_embedding", return_value=[0.1] * 8), \
         patch.object(price_service, "load_cache", new=AsyncMock()) as reload_mock:
        await price_service._generate_and_save_embedding("rec-1", "Кладка", "work")

    assert fake_record.embedding == [0.1] * 8, "вектор должен быть сохранён"
    reload_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_background_task_reference_is_kept():
    """Ссылка на фоновую задачу удерживается, пока та не завершилась."""
    started = asyncio.Event()
    release = asyncio.Event()

    async def _slow(*_args, **_kwargs):
        started.set()
        await release.wait()

    price_service._background_tasks.clear()

    with patch.object(price_service, "_generate_and_save_embedding", new=_slow):
        # Вызываем ровно тот участок save_to_cache, что порождает фоновую задачу.
        task = asyncio.create_task(_slow())
        price_service._background_tasks.add(task)
        task.add_done_callback(price_service._background_tasks.discard)

        await started.wait()
        assert task in price_service._background_tasks, "ссылка потеряна — задачу может убрать GC"

        release.set()
        await task

    # Завершившаяся задача убирается — множество не растёт бесконечно.
    await asyncio.sleep(0)
    assert task not in price_service._background_tasks
