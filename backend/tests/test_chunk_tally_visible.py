"""
Счётчик частей виден в истории обработки (план 2026-08-06-schetchik-chastey-v-logah.md).

Живая строка «готово N из M» идёт мимо progress_log, поэтому в истории задачи не
оставалось ни одной цифры о проделанной работе: пауза по балансу выглядела как
«отправили 9 частей — тишина». Здесь проверяется, что вехи и сообщения об обрыве
несут счёт частей.
"""
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.modules.setdefault("fitz", MagicMock())

from app.services.task_processor import TaskProcessor  # noqa: E402


def _proc() -> TaskProcessor:
    p = TaskProcessor("tid-tally", db=MagicMock())
    p.update_progress = AsyncMock(return_value=None)
    p.update_progress_message = AsyncMock(return_value=None)
    p._save_progress_data = AsyncMock(return_value=None)
    return p


# ---------------------------------------------------------------------------
# _chunk_tally_line — текст счётчика
# ---------------------------------------------------------------------------

def test_tally_line_reports_done_and_left():
    p = _proc()
    p._set_chunk_tally(9, label="Расчёт цен")
    p._note_chunk_progress(4)

    line = p._chunk_tally_line()
    assert "4" in line and "9" in line
    assert "5" in line, f"не сказано, сколько осталось: {line}"


def test_tally_line_empty_without_stage():
    """Этап чанков не начинался — приписывать нечего."""
    assert _proc()._chunk_tally_line() == ""


def test_tally_line_survives_overcount():
    """Остаток не уходит в минус, даже если применили больше частей, чем ожидали."""
    p = _proc()
    p._set_chunk_tally(2, label="Расчёт цен")
    p._note_chunk_progress(5)

    assert "-" not in p._chunk_tally_line()


def test_second_stage_does_not_reset_first_to_zero():
    """Повторный проход ведёт свой счёт, а не обнуляет общий."""
    p = _proc()
    p._set_chunk_tally(9, label="Расчёт цен")
    p._note_chunk_progress(9)
    p._set_chunk_tally(2, label="Повторный расчёт")

    line = p._chunk_tally_line()
    assert "Повторный расчёт" in line
    assert "0 из 2" in line


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


# ---------------------------------------------------------------------------
# Строка запуска этапа: реальное число отправляемых частей
# ---------------------------------------------------------------------------

def test_launch_line_mentions_restored_items():
    """После возобновления видно, что часть позиций не пойдёт в Claude повторно."""
    line = TaskProcessor._chunks_launch_line(matched=10, unmatched=137, pending_chunks=5, restored=42)
    assert "5" in line
    assert "42" in line


def test_launch_line_without_restore_is_plain():
    line = TaskProcessor._chunks_launch_line(matched=10, unmatched=137, pending_chunks=9, restored=0)
    assert "9" in line
    assert "уже посчитано" not in line


@pytest.mark.parametrize("restored", [0, 3])
def test_launch_line_always_reports_pending_not_total(restored):
    """Печатаем то, что реально отправляем, — иначе после resume кажется, что платим заново."""
    line = TaskProcessor._chunks_launch_line(matched=10, unmatched=137, pending_chunks=4, restored=restored)
    assert "4 чанк" in line
