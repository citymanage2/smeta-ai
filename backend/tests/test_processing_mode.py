"""
Tests for Task.processing_mode — режим обработки ESTIMATE_FROM_LIST.

'fast'  — параллельная обработка чанков (asyncio.gather)
'batch' — Anthropic Message Batches API (−50% стоимости, устойчивость к рестартам)

Phase 1 плана plans/2026-07-21-estimate-processing-modes.md.
"""
from app.models.task import Task


def test_processing_mode_column_exists_and_fits():
    """Колонка processing_mode существует, VARCHAR вмещает оба значения."""
    col = Task.__table__.c["processing_mode"]
    max_len = col.type.length
    assert max_len >= len("batch"), (
        f"processing_mode VARCHAR({max_len}) не вмещает 'batch'"
    )


async def test_processing_mode_defaults_to_fast(db_session):
    """Без явного значения processing_mode = 'fast'."""
    task = Task(
        user_role="user",
        task_type="ESTIMATE_FROM_LIST",
        input_files=[],
        input_file_data=[],
        chat_history=[],
    )
    db_session.add(task)
    await db_session.flush()
    await db_session.refresh(task)
    assert task.processing_mode == "fast"


async def test_processing_mode_accepts_batch(db_session):
    """Явное 'batch' сохраняется."""
    task = Task(
        user_role="user",
        task_type="ESTIMATE_FROM_LIST",
        input_files=[],
        input_file_data=[],
        chat_history=[],
        processing_mode="batch",
    )
    db_session.add(task)
    await db_session.flush()
    await db_session.refresh(task)
    assert task.processing_mode == "batch"
