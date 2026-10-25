"""
Phase 2b — промежуточный чекпоинт шага 2 ESTIMATE_FROM_LIST (fast/sync).

_pending_chunks: пропускает позиции, уже посчитанные Claude (resume без повторной
                 траты токенов).
Чекпоинт claude_partial: пауза посреди шага 2 сохраняет уже оплаченные ответы, и
                 возобновление шлёт в ИИ только непосчитанные позиции.

План: plans/2026-07-21-resume-and-balance-pause.md, Фаза 2б.
"""
from app.services.task_processor import TaskProcessor
from tests.helpers.anthropic_api import balance_error, prompt_text


# --------------------------------------------------------------------------
# _pending_chunks — исключает уже посчитанные позиции, дробит частичные чанки
# --------------------------------------------------------------------------

def test_pending_chunks_excludes_done_ids():
    chunks = [
        [{"_id": 0}, {"_id": 1}],   # 0 done, 1 pending → остаётся [1]
        [{"_id": 2}, {"_id": 3}],   # оба done → чанк выкидывается
        [{"_id": 4}],               # pending → остаётся
    ]
    pending = TaskProcessor._pending_chunks(chunks, {0, 2, 3})
    assert pending == [[{"_id": 1}], [{"_id": 4}]]


# --------------------------------------------------------------------------
# Чекпоинт claude_partial по кругу: пауза → возобновление без повторной оплаты.
# Прогон настоящий, на тестовой БД; подменён только ИИ.
# --------------------------------------------------------------------------

def _priced(prompt: str, answer: dict):
    """Ответ ИИ по позиции, которая в запросе: «Кладка» — цена, иначе `answer`."""
    if "Кладка стен" in prompt:
        return {"items": [{"id": 0, "type": "Работа", "work_price": 4500}]}
    return answer


async def test_resume_after_pause_sends_only_unpriced_positions(processor_env, claude_api):
    # Позиции на разных листах — две части шага 2: часть не пересекает лист.
    task = await processor_env.estimate_task([
        {"type": "Работа", "name": "Кладка стен", "unit": "м3", "quantity": 12, "sheet": "Раздел 1"},
        {"type": "Работа", "name": "Штукатурка стен", "unit": "м2", "quantity": 80, "sheet": "Раздел 2"},
    ])
    claude_api(lambda kw: _priced(prompt_text(kw), balance_error()), repeat=True)

    task = await processor_env.run(task)

    # Пауза посреди шага 2: оплаченная часть — в чекпоинте.
    assert task.status == "paused"
    assert task.progress_data["_stage"] == "claude_partial"
    assert task.progress_data["claude_results"]["0"]["work_price"] == 4500

    ai = claude_api(lambda kw: _priced(prompt_text(kw), {"items": [
        {"id": 1, "type": "Работа", "work_price": 650},
    ]}), repeat=True)
    task = await processor_env.run(task)

    assert task.status == "completed"
    # В ИИ ушла только непосчитанная позиция.
    (_call,) = ai.calls
    assert "Штукатурка стен" in ai.prompt(0) and "Кладка стен" not in ai.prompt(0)
    prices = {it["name"]: it["work_price"] for it in await processor_env.estimate_items(task)}
    assert prices == {"Кладка стен": 4500, "Штукатурка стен": 650}
