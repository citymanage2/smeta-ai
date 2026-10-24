"""
Счётчик частей виден в истории обработки (план 2026-08-06-schetchik-chastey-v-logah.md).

Живая строка «готово N из M» идёт мимо progress_log, поэтому в истории задачи не
оставалось ни одной цифры о проделанной работе: пауза по балансу выглядела как
«отправили 9 частей — тишина». Здесь проверяется, что вехи и сообщения об обрыве
несут счёт частей — в той истории, которую видит пользователь (`progress_log`).
"""


async def _history(processor_env, task) -> list[str]:
    return list((await processor_env.reload(task)).progress_log or [])


# ---------------------------------------------------------------------------
# Веха после группы и при обрыве — в историю, а не только в статус
# ---------------------------------------------------------------------------

async def test_milestone_goes_to_history(processor_env):
    task = await processor_env.task("ESTIMATE_FROM_LIST", status="processing")
    p = processor_env.processor(task)
    p._set_chunk_tally(9, label="Расчёт цен")

    await p._log_chunk_tally(3)

    (line,) = await _history(processor_env, task)
    assert "3" in line and "9" in line


async def test_milestone_silent_without_stage(processor_env):
    """Без начатого этапа чанков веха не пишется — лишних строк в истории нет."""
    task = await processor_env.task("ESTIMATE_FROM_LIST", status="processing")

    await processor_env.processor(task)._log_chunk_tally(1)

    assert await _history(processor_env, task) == []


# ---------------------------------------------------------------------------
# Сообщения об обрыве несут счётчик
# ---------------------------------------------------------------------------

async def test_pause_message_carries_tally(processor_env):
    """Пауза по балансу: в истории видно, сколько частей уже оплачено и сохранено."""
    task = await processor_env.task("ESTIMATE_FROM_LIST", status="processing")
    p = processor_env.processor(task)
    p._set_chunk_tally(9, label="Расчёт цен")
    p._note_chunk_progress(4)

    await p._report_stage_interrupted("⏸ На паузе: баланс API исчерпан.")

    (line,) = await _history(processor_env, task)
    assert "На паузе" in line
    assert "4" in line and "9" in line


async def test_interrupt_message_without_tally_is_unchanged(processor_env):
    task = await processor_env.task("ESTIMATE_FROM_LIST", status="processing")

    await processor_env.processor(task)._report_stage_interrupted("Ошибка: что-то пошло не так")

    assert await _history(processor_env, task) == ["Ошибка: что-то пошло не так"]
