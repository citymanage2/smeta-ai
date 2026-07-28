"""Единый предикат «у задачи есть чекпоинт для возобновления без потери прогресса».

Используется и ручным resume-эндпоинтом (app/routers/tasks.py: resume_task), и
авто-поллером paused-задач (app/services/resume_poller.py), чтобы обе ветки
возобновления вели себя одинаково и не расходились со временем.

Распознаваемые чекпоинты:
- `chunks_done`            — обработка чанков Claude уже начата;
- `ocr_pages_partial`      — по-страничный OCR частично выполнен (LIST_FROM_GRAND PDF);
- `ocr_pages`              — OCR завершён, чанки ещё не начаты;
- `_stage ∈ RESUMABLE_STAGES` — промежуточные стадии сохранения (pre_excel/claude_partial).

ВАЖНО (Фаза 8): отсутствие чекпоинта НЕ означает «возобновить нельзя». Пауза на
балансе может случиться до первого чекпоинта (первая группа чанков в fast-режиме
или submit пачки в batch-режиме) — тогда progress_data пуст, но задачу надо
перезапустить с нуля, иначе она мертва навсегда. Поэтому чекпоинт требуется
только для failed/cancelled (там пустой прогресс = «нечего продолжать»), а для
`paused` возобновление разрешено всегда.
"""
from __future__ import annotations

# Стадии, с которых поддерживается возобновление обработки Claude.
RESUMABLE_STAGES = ("pre_excel", "claude_partial")


def has_resumable_checkpoint(progress_data: dict | None) -> bool:
    pd = progress_data or {}
    return (
        "chunks_done" in pd
        or "ocr_pages_partial" in pd
        or "ocr_pages" in pd
        or pd.get("_stage") in RESUMABLE_STAGES
    )


def is_batch_pending(progress_data: dict | None) -> bool:
    """True, если пачка уже отправлена в Anthropic Batch API и ждёт результатов.

    Такую задачу НЕЛЬЗЯ перезапускать с нуля: пачка уже оплачена и считается на
    серверах Anthropic. Возобновление = вернуть задачу в `processing`, чтобы её
    добрал batch_poller (app/services/batch_poller.py).
    """
    pd = progress_data or {}
    return pd.get("_stage") == "batch_pending" and bool(pd.get("batch_id"))
