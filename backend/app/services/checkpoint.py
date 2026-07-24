"""Единый предикат «у задачи есть чекпоинт для возобновления без потери прогресса».

Используется и ручным resume-эндпоинтом (app/routers/tasks.py: resume_task), и
авто-поллером paused-задач (app/services/resume_poller.py), чтобы обе ветки
возобновления вели себя одинаково и не расходились со временем.

Распознаваемые чекпоинты:
- `chunks_done`            — обработка чанков Claude уже начата;
- `ocr_pages_partial`      — по-страничный OCR частично выполнен (LIST_FROM_GRAND PDF);
- `ocr_pages`              — OCR завершён, чанки ещё не начаты;
- `_stage ∈ RESUMABLE_STAGES` — промежуточные стадии сохранения (pre_excel/claude_partial).
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
