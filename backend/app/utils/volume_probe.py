"""Замер объёма работы задачи при её создании: сколько предстоит обработать.

Объём — основа прогноза «через сколько будет результат»: перечень на 40 позиций
и на 1200 считаются на порядок разное время. Замер делается один раз, при
создании (файлы ещё в памяти), и живёт в `tasks.volume_units` / `volume_kind`.

Принцип: замер НИКОГДА не мешает создать задачу. Любая проблема с файлом →
`(None, None)`, задача создаётся штатно, прогноз просто строится по медиане типа.
Поэтому все ветки обёрнуты в широкий except — это осознанно, а не небрежность.
"""
import io
from typing import Optional, Sequence

import structlog

logger = structlog.get_logger()

# Единицы объёма. Разные типы задач меряются разным, и смешивать их в одной
# ставке «секунд на единицу» нельзя — страница проекта и строка сметы стоят
# принципиально разного времени.
UNIT_PAGES = "pages"
UNIT_ROWS = "rows"
UNIT_ITEMS = "items"

# Потолок: защита от абсурдных значений (битый xlsx с миллионом пустых строк,
# которые openpyxl всё же считает непустыми из-за форматирования).
_MAX_UNITS = 100_000

_XLSX_MIMES = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
}
_IMAGE_MIMES = {"image/jpeg", "image/png"}


def _clamp(n: int) -> Optional[int]:
    if n <= 0:
        return None
    return min(n, _MAX_UNITS)


def _pdf_pages(data: bytes) -> Optional[int]:
    from app.utils.pdf_ocr_extractor import get_pdf_page_count

    return _clamp(int(get_pdf_page_count(data)))


def _xlsx_rows(data: bytes) -> Optional[int]:
    """Число непустых строк во всех листах книги.

    `read_only=True` — потоковое чтение: файл на 50 МБ не разворачивается в
    объектную модель целиком. Считаем строки, а не «позиции»: разметка смет у
    разных подрядчиков своя, а для оценки времени важен порядок величины.
    """
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        total = 0
        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True):
                if any(cell is not None and str(cell).strip() for cell in row):
                    total += 1
                    if total >= _MAX_UNITS:
                        return _MAX_UNITS
        return _clamp(total)
    finally:
        wb.close()


def probe_file_units(mime_type: str, file_name: str, data: bytes) -> tuple[Optional[int], Optional[str]]:
    """Объём одного файла: (сколько единиц, в чём меряем). Не бросает."""
    name = (file_name or "").lower()
    mime = (mime_type or "").lower()
    try:
        if mime == "application/pdf" or name.endswith(".pdf"):
            pages = _pdf_pages(data)
            return (pages, UNIT_PAGES) if pages else (None, None)
        if mime in _XLSX_MIMES or name.endswith((".xlsx", ".xls")):
            rows = _xlsx_rows(data)
            return (rows, UNIT_ROWS) if rows else (None, None)
        if mime in _IMAGE_MIMES:
            # Скан-страница: одна картинка — одна страница для OCR.
            return 1, UNIT_PAGES
    except Exception as e:  # noqa: BLE001 — замер объёма не вправе ломать создание задачи
        logger.info("Volume probe failed, ETA will fall back to type median",
                    file=file_name, error=str(e))
    # XML-выгрузка Гранд-сметы и прочие форматы: разметка не гарантирована,
    # гадать не будем — прогноз построится по медиане типа задачи.
    return None, None


def probe_files_units(
    files: Sequence[tuple[str, str, bytes]]
) -> tuple[Optional[int], Optional[str]]:
    """Объём набора файлов: суммируем по каждой единице и берём преобладающую.

    Смешанная загрузка (PDF + xlsx) в проекте бывает; складывать страницы со
    строками бессмысленно, поэтому побеждает та единица, которой больше всего.
    """
    totals: dict[str, int] = {}
    for mime_type, file_name, data in files:
        units, kind = probe_file_units(mime_type, file_name, data)
        if units and kind:
            totals[kind] = totals.get(kind, 0) + units
    if not totals:
        return None, None
    kind = max(totals, key=lambda k: totals[k])
    return _clamp(totals[kind]), kind


def probe_items_units(progress_data: Optional[dict]) -> tuple[Optional[int], Optional[str]]:
    """Объём задачи, работающей по готовому перечню (Path B, проверки полноты).

    Позиции уже посчитаны предыдущей задачей и лежат в её `progress_data`.
    """
    items = (progress_data or {}).get("items")
    if isinstance(items, list) and items:
        return _clamp(len(items)), UNIT_ITEMS
    return None, None
