"""Whitelist-сериализатор прогресса задачи для отдачи на фронт.

`Task.progress_data` (JSONB) хранит не только счётчики прогресса, но и тяжёлые /
чувствительные данные обработки: сами позиции сметы с ценами (`items`), сырой
OCR-текст страниц PDF (`ocr_pages` / `ocr_pages_partial`), ответы модели
(`claude_results`), сопоставления с прайсом (`matched` / `unmatched`), предложения
оптимизации (`proposals`), ABC-разбивку, внутренние id пачек (`batch_id`) и т.п.

Наружу (в лёгкий `TaskBrief` карточек-смет) отдаём ТОЛЬКО скалярные поля прогресса
по белому списку — этого достаточно для счётчика «N из M», но не утекает контент
входных файлов, промптов, цен или вывода модели.
"""
from typing import Any, Optional

# Целочисленные счётчики прогресса — безопасны, нужны для «N из M».
_INT_FIELDS = ("chunks_done", "total_chunks", "chunks_total", "partial_count")
# Скалярные строковые метки стадии — безопасны (перечислимые значения).
_STR_FIELDS = ("opt_step", "status")


def build_progress_summary(progress_data: Optional[dict]) -> Optional[dict]:
    """Вернуть безопасную выжимку прогресса или None.

    Отдаёт только поля из белого списка + производный `items_count` (ДЛИНА списка
    позиций, без самого содержимого). Всё остальное (items, ocr_pages,
    claude_results, matched, proposals, batch_id, _stage, error, …) намеренно
    отбрасывается.
    """
    if not isinstance(progress_data, dict) or not progress_data:
        return None

    out: dict[str, Any] = {}

    for key in _INT_FIELDS:
        val = progress_data.get(key)
        # bool — подкласс int, исключаем явно.
        if isinstance(val, bool):
            continue
        if isinstance(val, int):
            out[key] = val

    for key in _STR_FIELDS:
        val = progress_data.get(key)
        if isinstance(val, str) and val:
            out[key] = val

    # Кол-во накопленных позиций — только длина, не содержимое.
    items = progress_data.get("items")
    if isinstance(items, list):
        out["items_count"] = len(items)

    # Оптимизация пишет ключ `chunks_total`; нормализуем к `total_chunks`,
    # чтобы фронт читал один ключ.
    if "total_chunks" not in out and "chunks_total" in out:
        out["total_chunks"] = out["chunks_total"]

    return out or None
