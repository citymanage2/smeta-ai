"""Запись и чтение снимка «что выдал ИИ».

План: plans/2026-09-10-sverka-i-obuchenie-na-pravkah.md, Фаза 1.

Два правила, без которых снимок бесполезен или вреден:

1. **Пишется один раз.** Задачу можно перезапустить (resume, batch, повторный
   расчёт), и второй проход придёт сюда уже после того, как человек успел
   поправить строки. Запись идёт только при отсутствии снимка; гонку двух
   процессов ловит уникальный индекс `(task_id, document_kind)`, и повторная
   попытка молча не делает ничего.
2. **Снимок — копия тех строк, что легли в рабочую версию**, а не повторный
   разбор файла. `xlsx_generic.parse_xlsx_to_generic_rows` выдаёт новый `row_id`
   на каждый разбор, поэтому снимок, собранный вторым разбором, не сопоставился
   бы ни с одной сегодняшней строкой — сверка показала бы «ИИ выдал 500 позиций,
   человек заменил все 500».

Сбой записи снимка никогда не роняет расчёт: снимок полезен, но смета важнее.
Это то же правило, по которому живёт журнал корректировок.
"""
from __future__ import annotations

import copy
from typing import Optional

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_baseline import MAX_BASELINE_ROWS, AiBaseline

logger = structlog.get_logger()

# Типы документов, у которых есть первичный вывод ИИ. Оптимизация и раздел
# сводной сюда не входят: их строки — работа над уже посчитанной сметой, а не
# ответ модели на исходные данные.
BASELINE_KINDS = frozenset({"list", "completeness", "estimate"})


async def save_once(
    db: AsyncSession,
    *,
    task_id: str,
    document_kind: str,
    rows: Optional[list],
    edited_at: Optional[object] = None,
    commit: bool = True,
) -> bool:
    """Сохранить снимок, если его ещё нет. True — снимок записан этим вызовом.

    `edited_at` — `task.manually_edited_at`. Заполнен, значит строки уже трогал
    человек, и снимок с них был бы не «что выдал ИИ», а «что осталось после
    правок» — молчаливая ложь в отчёте о качестве. Такую задачу оставляем без
    снимка: пустой ответ честнее выдуманного (то же правило, что у номеров
    позиций, №7 CLAUDE.md).

    Никогда не бросает: снимок не важнее расчёта, ради которого его пишут.
    """
    try:
        return await _save_once(
            db, task_id=task_id, document_kind=document_kind, rows=rows,
            edited_at=edited_at, commit=commit,
        )
    except Exception as error:  # noqa: BLE001 — снимок не важнее расчёта
        logger.warning(
            "ai_baseline_save_failed",
            task_id=task_id, kind=document_kind, error=str(error),
        )
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return False


async def _save_once(
    db: AsyncSession,
    *,
    task_id: str,
    document_kind: str,
    rows: Optional[list],
    edited_at: Optional[object],
    commit: bool,
) -> bool:
    if document_kind not in BASELINE_KINDS:
        return False
    if edited_at is not None:
        logger.info(
            "ai_baseline_skipped_edited", task_id=task_id, kind=document_kind,
        )
        return False
    if not rows:
        # Пустой расчёт снимком не является: сверять будет нечего, а запись
        # заняла бы пару «задача + документ» и закрыла бы дорогу настоящему
        # снимку при следующем проходе.
        return False

    existing = await db.scalar(
        select(AiBaseline.id).where(
            AiBaseline.task_id == task_id,
            AiBaseline.document_kind == document_kind,
        )
    )
    if existing is not None:
        return False

    total = len(rows)
    truncated = total > MAX_BASELINE_ROWS
    kept = rows[:MAX_BASELINE_ROWS] if truncated else rows

    db.add(AiBaseline(
        task_id=task_id,
        document_kind=document_kind,
        # Глубокая копия: строки после этого вызова продолжают жить своей
        # жизнью (их пишут в версию, пересобирают, правят), а снимок обязан
        # остаться таким, каким был в этот момент.
        rows=copy.deepcopy(kept),
        row_count=total,
        truncated=truncated,
    ))
    try:
        if commit:
            await db.commit()
        else:
            await db.flush()
    except IntegrityError:
        # Снимок успел записать параллельный процесс — ровно то, чего мы хотели.
        await db.rollback()
        return False

    if truncated:
        logger.info(
            "ai_baseline_truncated",
            task_id=task_id, kind=document_kind, rows=total, kept=MAX_BASELINE_ROWS,
        )
    return True


async def read(
    db: AsyncSession, *, task_id: str, document_kind: str
) -> Optional[AiBaseline]:
    """Снимок задачи или None, если его нет (задача посчитана до этой функции)."""
    result = await db.execute(
        select(AiBaseline).where(
            AiBaseline.task_id == task_id,
            AiBaseline.document_kind == document_kind,
        )
    )
    return result.scalar_one_or_none()
