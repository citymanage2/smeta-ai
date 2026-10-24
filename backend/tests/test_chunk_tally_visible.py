"""
Счётчик частей виден в истории обработки (план 2026-08-06-schetchik-chastey-v-logah.md).

Живая строка «готово N из M» идёт мимо progress_log, поэтому в истории задачи не
оставалось ни одной цифры о проделанной работе: пауза по балансу выглядела как
«отправили 9 частей — тишина». Здесь проверяется, что вехи и сообщения об обрыве
несут счёт частей.
"""
import sys
from unittest.mock import AsyncMock, MagicMock

sys.modules.setdefault("fitz", MagicMock())

from app.services.task_processor import TaskProcessor  # noqa: E402


def _proc() -> TaskProcessor:
    p = TaskProcessor("tid-tally", db=MagicMock())
    p.update_progress = AsyncMock(return_value=None)
    p.update_progress_message = AsyncMock(return_value=None)
    p._save_progress_data = AsyncMock(return_value=None)
    return p


# ---------------------------------------------------------------------------
# Веха после группы и при обрыве — в историю, а не только в статус
# ---------------------------------------------------------------------------

async def test_milestone_goes_to_history():
    p = _proc()
    p._set_chunk_tally(9, label="Расчёт цен")

    await p._log_chunk_tally(3)

    p.update_progress.assert_awaited()
    written = " ".join(c.args[0] for c in p.update_progress.await_args_list)
    assert "3" in written and "9" in written


async def test_milestone_silent_without_stage():
    """Без начатого этапа чанков веха не пишется — лишних строк в истории нет."""
    p = _proc()
    await p._log_chunk_tally(1)
    p.update_progress.assert_not_awaited()


# ---------------------------------------------------------------------------
# Сообщения об обрыве несут счётчик
# ---------------------------------------------------------------------------

async def test_pause_message_carries_tally():
    """Пауза по балансу: в истории видно, сколько частей уже оплачено и сохранено."""
    p = _proc()
    p._set_chunk_tally(9, label="Расчёт цен")
    p._note_chunk_progress(4)

    await p._report_stage_interrupted("⏸ На паузе: баланс API исчерпан.")

    written = " ".join(c.args[0] for c in p.update_progress.await_args_list)
    assert "На паузе" in written
    assert "4" in written and "9" in written


async def test_interrupt_message_without_tally_is_unchanged():
    p = _proc()
    await p._report_stage_interrupted("Ошибка: что-то пошло не так")

    written = " ".join(c.args[0] for c in p.update_progress.await_args_list)
    assert written == "Ошибка: что-то пошло не так"
