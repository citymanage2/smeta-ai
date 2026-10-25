"""
Живой прогресс и предельный срок внутри пачки чанков.

Два дефекта, из-за которых задача выглядела мёртвой:

1. ТИШИНА. `_process_chunks` пишет одно сообщение перед всей пачкой (до 38
   запросов) и следующее — только после группы. Между ними в UI ничего не
   меняется десятки минут. Воркерам нельзя трогать self.db (конкурентный доступ
   к AsyncSession), поэтому счётчик готовых публикует cancel-watcher — он и так
   единственный, кто ходит в self.db.

2. НЕТ ПРЕДЕЛА. При недоступном API автоповтор с бэкоффом до 900 с растягивает
   пачку на часы. Нужен дедлайн: отменить незавершённые и упасть с внятной
   ошибкой, отличимой от нажатия «Стоп», чтобы уже оплаченные чанки успели
   примениться и попасть в чекпоинт.

План: plans/2026-07-29-diagnostika-v-admin-panel.md, Фазы 2–3.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.task_processor import (
    TaskProcessor,
    StageDeadlineError,
    _chunk_stage_deadline,
    CHUNK_STAGE_DEADLINE_S,
)


# ---------------------------------------------------------------------------
# Дедлайн должен расти вместе с размером пачки
# ---------------------------------------------------------------------------

def test_deadline_scales_with_batch_size():
    """Пачка на 30 чанков штатно идёт ~24 мин при параллельности 4 — фиксированные
    30 минут обрывали бы здоровую работу. Дедлайн растёт вместе с пачкой и
    оставляет здоровой работе заметный запас: цель — поймать зависание (часы)."""
    small = _chunk_stage_deadline(8, 4)
    large = _chunk_stage_deadline(30, 4)
    assert large > small
    assert large >= 2 * 24 * 60


def test_deadline_never_below_floor():
    """У крошечной пачки дедлайн не должен схлопываться до минут."""
    assert _chunk_stage_deadline(1, 4) >= CHUNK_STAGE_DEADLINE_S
    assert _chunk_stage_deadline(0, 4) >= CHUNK_STAGE_DEADLINE_S


def test_deadline_survives_zero_concurrency():
    """concurrency=0 не должен делить на ноль."""
    assert _chunk_stage_deadline(10, 0) >= CHUNK_STAGE_DEADLINE_S


def _proc() -> TaskProcessor:
    p = TaskProcessor("tid-1", db=MagicMock())
    p._check_cancelled = AsyncMock(return_value=None)
    p.update_progress_message = AsyncMock(return_value=None)
    return p


# ---------------------------------------------------------------------------
# Фаза 2 — живой счётчик готовых чанков
# ---------------------------------------------------------------------------

async def test_progress_published_while_chunks_run():
    """Пока пачка идёт, в progress_message капает «готово N из M»."""
    p = _proc()

    def make(delay):
        async def _w():
            await asyncio.sleep(delay)
            return delay
        return _w

    workers = [make(0.02), make(0.04), make(0.06)]
    await p._run_chunks_parallel(
        workers,
        concurrency=3,
        progress_tick=0.01,          # частый тик, чтобы тест был быстрым
        progress_label="Обработано {done} из {total} частей...",
    )

    published = [c.args[0] for c in p.update_progress_message.await_args_list]
    assert published, "во время пачки не опубликовано ни одного сообщения"
    assert any("из 3 частей" in m for m in published)
    # Счётчик должен расти, а не залипнуть на нуле.
    assert any(m.startswith("Обработано 1 ") or m.startswith("Обработано 2 ") for m in published)


async def test_progress_does_not_pollute_history_log(processor_env):
    """Живая строка идёт мимо progress_log — иначе «ХОД ВЫПОЛНЕНИЯ» раздуется."""
    task = await processor_env.task("ESTIMATE_FROM_LIST", status="processing")
    label = "Обработано {done} из {total} частей..."

    def make(delay):
        async def _w():
            await asyncio.sleep(delay)
            return delay
        return _w

    await processor_env.processor(task)._run_chunks_parallel(
        [make(0.02), make(0.08)], concurrency=2, progress_tick=0.01, progress_label=label,
    )

    task = await processor_env.reload(task)
    # Строка статуса живая: в ней счёт этой пачки.
    assert task.progress_message in {label.format(done=d, total=2) for d in range(3)}
    # А в историю задачи тики не попали.
    assert task.progress_log in (None, [])


# ---------------------------------------------------------------------------
# Фаза 3 — предельный срок пачки
# ---------------------------------------------------------------------------

async def test_deadline_cancels_hanging_chunks():
    """Зависшая пачка обрывается по дедлайну, а не висит вечно."""
    p = _proc()

    async def _hang():
        await asyncio.sleep(60)
        return "never"

    with pytest.raises(StageDeadlineError):
        await p._run_chunks_parallel(
            [_hang, _hang], concurrency=2, deadline_s=0.05, progress_tick=0.01
        )


async def test_deadline_keeps_finished_chunks_with_return_exceptions():
    """Успевшие чанки уже оплачены — они возвращаются, а не теряются."""
    p = _proc()

    async def _fast():
        return "paid"

    async def _hang():
        await asyncio.sleep(60)
        return "never"

    results = await p._run_chunks_parallel(
        [_fast, _hang], concurrency=2, deadline_s=0.05,
        progress_tick=0.01, return_exceptions=True,
    )

    assert results[0] == "paid"
    # Незавершённый приходит как StageDeadlineError, а НЕ CancelledError —
    # иначе caller решит, что пользователь нажал «Стоп».
    assert isinstance(results[1], StageDeadlineError)
