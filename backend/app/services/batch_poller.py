"""
Периодический поллер задач ESTIMATE_FROM_LIST в batch-режиме.

Batch считается на серверах Anthropic (устойчив к рестартам). Этот поллер
запускается по расписанию (apscheduler в main.py), находит задачи с
progress_data._stage == 'batch_pending', опрашивает пачку и по завершении
достраивает смету через TaskProcessor.resume_from_batch.

Логика вынесена из main.py, чтобы не тянуть apscheduler в тесты.
План: plans/2026-07-21-estimate-processing-modes.md, Phase 5.
"""
import structlog
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.task import Task
from app.services.claude_service import (
    poll_claude_batch,
    cancel_claude_batch,
    InsufficientBalanceError,
)
from app.services.task_processor import TaskProcessor

logger = structlog.get_logger()

_BATCH_PENDING = "batch_pending"


async def _find_batch_pending_ids(db) -> list[str]:
    """ID задач в состоянии batch_pending (Python-фильтр — DB-agnostic)."""
    result = await db.execute(
        select(Task).where(Task.status.in_(["processing", "cancelled"]))
    )
    return [
        t.id
        for t in result.scalars().all()
        if (t.progress_data or {}).get("_stage") == _BATCH_PENDING
    ]


async def _process_one(task_id: str, db) -> None:
    """Обработать одну batch_pending задачу в переданной сессии."""
    task = await db.get(Task, task_id)
    if not task:
        return
    pdata = task.progress_data or {}
    if pdata.get("_stage") != _BATCH_PENDING:
        return

    batch_id = pdata.get("batch_id")
    processor = TaskProcessor(task_id, db)

    # Отмена: пользователь остановил задачу — отменяем пачку и снимаем _stage.
    if task.status == "cancelled":
        if batch_id:
            try:
                await cancel_claude_batch(batch_id)
            except Exception as e:
                logger.warning("Failed to cancel batch", task_id=task_id, error=str(e))
        new_pdata = dict(pdata)
        new_pdata["_stage"] = "batch_cancelled"
        await processor._save_progress_data(new_pdata)
        logger.info("Batch task cancelled", task_id=task_id, batch_id=batch_id)
        return

    if not batch_id:
        await processor.update_status("failed", error="Batch: отсутствует batch_id")
        return

    try:
        status = await poll_claude_batch(batch_id)
    except Exception as e:
        logger.warning("Batch poll failed, will retry", task_id=task_id, error=str(e))
        return  # повторим на следующем тике

    if status in ("in_progress", "canceling"):
        return  # ещё считается

    if status == "ended":
        try:
            await processor.resume_from_batch(task)
            await processor._auto_fill_estimate_slot()
            await processor.update_status("completed")
            logger.info("Batch task completed", task_id=task_id, batch_id=batch_id)
        except InsufficientBalanceError:
            # Баланс кончился на сборке пачки — не failed, а пауза: чекпоинт
            # batch_pending сохранён, resume_poller вернёт задачу в processing и
            # поллер доберёт те же (уже оплаченные) результаты.
            logger.warning("Batch task paused — API balance exhausted", task_id=task_id)
            await processor.update_status(
                "paused",
                error="Баланс API Anthropic исчерпан. Задача продолжится автоматически после пополнения счёта.",
            )
            await processor.update_progress(
                "⏸ На паузе: баланс API исчерпан. Возобновление произойдёт автоматически после пополнения."
            )
        except Exception as e:
            logger.error("Batch resume failed", task_id=task_id, error=str(e))
            await processor.update_status(
                "failed", error=f"Ошибка сборки сметы из batch: {e}"
            )
        return

    # canceled / expired / неизвестный статус
    logger.warning("Batch ended abnormally", task_id=task_id, status=status)
    await processor.update_status(
        "failed", error=f"Пакетная обработка завершилась статусом: {status}"
    )


async def poll_batch_tasks(session_factory=AsyncSessionLocal) -> None:
    """Один проход поллера: найти batch_pending задачи и обработать каждую
    в своей сессии (изоляция AsyncSession)."""
    async with session_factory() as db:
        task_ids = await _find_batch_pending_ids(db)

    if not task_ids:
        return

    logger.info("Polling batch tasks", count=len(task_ids))
    for task_id in task_ids:
        try:
            async with session_factory() as db:
                await _process_one(task_id, db)
        except Exception as e:
            logger.error("Batch poll iteration failed", task_id=task_id, error=str(e))
