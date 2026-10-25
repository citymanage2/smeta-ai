"""
Фаза 2 — по-чанковый чекпоинт и resume для LIST_FROM_PROJECT.

Контракт:
- Проход 1 (извлечение позиций из PDF по чанкам) пишет чекпоинт после каждого
  чанка (`chunks_done`, `_stage="pass1"`); resume продолжает с необработанных
  частей, не пересчитывая уже обработанные.
- После прохода 1 ставится `_stage="pass1_done"`, чтобы пауза в проходе 2 не
  перезапускала дорогой проход 1.
- Баланс API (InsufficientBalanceError) в любом чанке НЕ проглатывается, а
  пробрасывается вверх (→ пауза) — раньше non-first чанк молча пропускался.

Прогон настоящий: PDF проекта лежит во входных файлах задачи, задача и её
чекпоинты — в тестовой БД, подменён только ИИ. Возобновление — второй прогон той
же задачи после паузы, как это делает воркер.

План: plans/2026-07-21-resume-and-balance-pause.md, Фаза 2.
"""
import fitz
import pytest
from sqlalchemy import select

from app.models.estimate_version import EstimateVersion
from tests.helpers.anthropic_api import balance_error, claude_message, prompt_text

PART_1 = "Страница 1 ---"
PART_2 = "Страница 2 ---"

DUCT_WORK = {"type": "Работа", "name": "Монтаж воздуховодов", "unit": "м2", "quantity": 120}
DUCT = {"type": "Материал", "name": "Воздуховод оцинкованный", "unit": "м2", "quantity": 126}


@pytest.fixture(scope="module")
def project_pdf() -> bytes:
    """PDF проекта из двух текстовых страниц; первая длиннее порога части, поэтому
    документ уходит в ИИ двумя частями — по странице на часть."""
    doc = fitz.open()
    page = doc.new_page(width=842, height=1191)
    page.insert_textbox(
        fitz.Rect(10, 10, 832, 1181), " ".join(f"section{i}" for i in range(4500)), fontsize=4,
    )
    page = doc.new_page()
    page.insert_textbox(
        fitz.Rect(36, 36, 559, 806), " ".join(f"appendix{i}" for i in range(60)), fontsize=10,
    )
    data = doc.tobytes()
    doc.close()
    return data


def _by_part(part_1, part_2, pass_2=None):
    """Ответ ИИ по тому, какую часть PDF ему прислали (или уточнение объёмов)."""
    def answer(kwargs):
        prompt = prompt_text(kwargs)
        if PART_1 in prompt:
            return part_1
        if PART_2 in prompt:
            return part_2
        assert pass_2 is not None, "неожиданный запрос уточнения объёмов"
        return pass_2
    return answer


async def _project_task(processor_env, project_pdf):
    task = await processor_env.task(
        "LIST_FROM_PROJECT", input_files=[{"name": "Проект.pdf", "mime_type": "application/pdf"}],
    )
    await processor_env.input_file(task, "Проект.pdf", "application/pdf", project_pdf)
    return task


async def _list_names(processor_env, task) -> list[str]:
    """Наименования позиций в документе перечня (версия V0 — её видит редактор)."""
    task_id = str((await processor_env.reload(task)).id)
    version = (await processor_env.db.execute(
        select(EstimateVersion).where(
            EstimateVersion.task_id == task_id, EstimateVersion.file_slot == "result",
        )
    )).scalar_one()
    return [row["cells"]["Наименование"] for row in version.rows]


# ---------------------------------------------------------------------------
# Баланс в non-first чанке прохода 1 → пауза с чекпоинтом (не проглатывается)
# ---------------------------------------------------------------------------

async def test_balance_error_in_pass1_propagates(processor_env, claude_api, project_pdf):
    claude_api(_by_part({"items": [DUCT_WORK]}, balance_error()), repeat=True)
    task = await _project_task(processor_env, project_pdf)

    task = await processor_env.run(task)

    # Задача не завершилась и не упала, а ушла на паузу.
    assert task.status == "paused"
    # Чекпоинт после успешного чанка 0 сохранён — resume продолжит с чанка 1.
    checkpoint = task.progress_data
    assert checkpoint["_stage"] == "pass1"
    assert (checkpoint["chunks_done"], checkpoint["total_chunks"]) == (1, 2)
    assert [it["name"] for it in checkpoint["items"]] == ["Монтаж воздуховодов"]
    assert await processor_env.results(task) == []


# ---------------------------------------------------------------------------
# Resume прохода 1 — пропуск уже обработанных чанков
# ---------------------------------------------------------------------------

async def test_resume_pass1_skips_done_chunks(processor_env, claude_api, project_pdf):
    claude_api(_by_part({"items": [DUCT_WORK]}, balance_error()), repeat=True)
    task = await processor_env.run(await _project_task(processor_env, project_pdf))
    assert task.status == "paused"

    ai = claude_api(_by_part(AssertionError("часть 1 уже посчитана"), {"items": [DUCT]}), repeat=True)
    task = await processor_env.run(task)

    assert task.status == "completed"
    # В ИИ ушла только вторая часть — первая взята из чекпоинта.
    (_call,) = ai.calls
    assert PART_2 in ai.prompt(0) and PART_1 not in ai.prompt(0)
    assert await _list_names(processor_env, task) == ["Монтаж воздуховодов", "Воздуховод оцинкованный"]


async def test_resume_pass1_done_skips_pass1_entirely(processor_env, claude_api, project_pdf):
    """Пауза во втором проходе (уточнение объёмов) — возобновление не повторяет первый."""
    unknown_qty = {**DUCT_WORK, "quantity": None}
    claude_api(_by_part({"items": [unknown_qty]}, {"items": [DUCT]}, balance_error()), repeat=True)
    task = await processor_env.run(await _project_task(processor_env, project_pdf))
    assert task.status == "paused"
    assert task.progress_data["_stage"] == "pass1_done"

    ai = claude_api(
        _by_part(AssertionError("проход 1 уже сделан"), AssertionError("проход 1 уже сделан"),
                 {"items": [DUCT_WORK]}),
        repeat=True,
    )
    task = await processor_env.run(task)

    assert task.status == "completed"
    # Ни одной части PDF повторно — только уточнение объёма.
    (_call,) = ai.calls
    assert PART_1 not in ai.prompt(0) and PART_2 not in ai.prompt(0)
    assert await _list_names(processor_env, task) == ["Монтаж воздуховодов", "Воздуховод оцинкованный"]


async def test_first_chunk_failure_raises(processor_env, claude_api, project_pdf):
    """Регрессия: падение самого первого чанка (не баланс) по-прежнему валит задачу."""
    truncated = claude_message({"items": []}, stop_reason="max_tokens")
    ai = claude_api(_by_part(truncated, {"items": [DUCT]}), repeat=True)
    task = await _project_task(processor_env, project_pdf)

    task = await processor_env.run(task)

    assert task.status == "failed"
    assert len(ai.calls) == 1
    assert await processor_env.results(task) == []
