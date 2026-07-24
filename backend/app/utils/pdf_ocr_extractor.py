"""Извлечение текста из PDF: embedded-текст через PyMuPDF, сканы — через Tesseract OCR."""

from __future__ import annotations

import gc
import resource

import structlog

logger = structlog.get_logger(__name__)


def _peak_rss_mb() -> int:
    """Пиковое потребление RSS процессом, МБ. Монотонно растёт — high-water mark.

    Логируется вокруг OCR, чтобы при повторных рестартах инстанса подтвердить/опровергнуть
    OOM без доступа к метрикам хостинга. Linux даёт ru_maxrss в КБ, macOS — в байтах.
    """
    ru = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # эвристика единиц: значения > 10^7 почти наверняка в байтах (macOS)
    return round(ru / (1024 * 1024)) if ru > 10_000_000 else round(ru / 1024)

try:
    import pytesseract
    _TESSERACT_AVAILABLE = True
except ImportError:
    _TESSERACT_AVAILABLE = False

import fitz  # PyMuPDF


def extract_pdf_with_ocr(pdf_bytes: bytes) -> list[dict]:
    """Открывает PDF и возвращает список страниц с текстом.

    Каждый элемент: {"page": int, "text": str, "method": "embedded"|"ocr"}

    Raises ValueError для некорректных/неподдерживаемых PDF.
    """
    # A3: обёртка вокруг fitz.open
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        raise ValueError(f"Не удалось открыть PDF: {e}") from e

    # A1: пустой PDF
    if len(doc) == 0:
        raise ValueError("PDF не содержит страниц")

    # A2: PDF с паролем
    if doc.needs_pass:
        raise ValueError("PDF защищён паролем — снимите защиту перед загрузкой")

    # A4: слишком большой PDF
    if len(doc) > 150:
        raise ValueError(
            f"PDF слишком большой ({len(doc)} стр.). Разбейте на части по 100 страниц."
        )

    pages: list[dict] = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        result = _process_page(page, page_num + 1)
        pages.append(result)

    doc.close()
    return pages


def _process_page(page: fitz.Page, page_num: int) -> dict:
    """Обрабатывает одну страницу: embedded-текст или OCR."""
    text = page.get_text().strip()
    words = text.split()

    # D1: валидация по доле кириллицы
    cyrillic_count = sum(1 for c in text if "Ѐ" <= c <= "ӿ")
    cyrillic_ratio = cyrillic_count / max(len(text), 1)

    if len(words) >= 30 and cyrillic_ratio >= 0.10:
        return {"page": page_num, "text": text, "method": "embedded"}

    # Скан или плохая кодировка — OCR
    return _ocr_page(page, page_num)


def _render_page_image(page: fitz.Page):
    """Растеризует страницу в PIL Image (grayscale) для OCR.

    B1: dpi=150 (уменьшено с 200 для экономии памяти), ограничение ширины 2480px.
    Grayscale (csGRAY) вместо RGB: Tesseract всё равно бинаризует изображение внутри,
    поэтому точность распознавания не меняется, а память под pixmap и вход Tesseract
    втрое меньше (1 байт/пиксель вместо 3) — критично для инстанса с ограниченной RAM.
    """
    dpi = 150
    scale = dpi / 72.0

    page_width_at_scale = page.rect.width * scale
    if page_width_at_scale > 2480:
        scale = 2480 / page.rect.width

    matrix = fitz.Matrix(scale, scale)

    # B2: pixmap создаём и сразу освобождаем после получения PIL Image
    pix = page.get_pixmap(matrix=matrix, colorspace=fitz.csGRAY)
    # B3: PIL Image напрямую без PNG round-trip
    img = pix.pil_image()
    pix = None  # освобождаем память
    gc.collect()
    return img


def _ocr_page(page: fitz.Page, page_num: int) -> dict:
    """Растеризует страницу и запускает Tesseract OCR."""
    if not _TESSERACT_AVAILABLE:
        # C1: Tesseract не установлен
        raise ValueError("OCR-движок не установлен. Обратитесь к администратору.")

    img = _render_page_image(page)

    logger.info("ocr_start", page=page_num, peak_rss_mb=_peak_rss_mb())

    timed_out = False
    try:
        # C3: таймаут 60 сек на страницу (на 0.5 CPU Tesseract иногда не укладывается в 30с)
        ocr_text = pytesseract.image_to_string(img, lang="rus+eng", timeout=60)
    except RuntimeError:
        # C6: таймаут — помечаем страницу как нераспознанную, чтобы выше её не потеряли молча
        logger.warning("ocr_timeout", page=page_num)
        ocr_text = ""
        timed_out = True
    except pytesseract.pytesseract.TesseractNotFoundError:
        # C1: Tesseract не найден в системе
        raise ValueError("OCR-движок не установлен. Обратитесь к администратору.")
    finally:
        del img
        gc.collect()

    logger.info("ocr_end", page=page_num, peak_rss_mb=_peak_rss_mb())

    result = {"page": page_num, "text": ocr_text.strip(), "method": "ocr"}
    if timed_out:
        # Флаг для вызывающего кода: страница НЕ распозналась, текст потерян —
        # перечень по ней будет неполным (см. timed_out_page_numbers).
        result["ocr_timeout"] = True
    return result


def timed_out_page_numbers(pages: list[dict]) -> list[int]:
    """Номера страниц, где OCR не уложился в таймаут (их текст потерян → перечень неполон)."""
    return [p["page"] for p in pages if p.get("ocr_timeout")]


def get_pdf_page_count(pdf_bytes: bytes) -> int:
    """Возвращает число страниц PDF без полной обработки."""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        count = len(doc)
        doc.close()
        return count
    except Exception as e:
        raise ValueError(f"Не удалось открыть PDF: {e}") from e


def extract_single_page(pdf_bytes: bytes, page_idx: int) -> dict:
    """Обрабатывает одну страницу PDF (0-indexed). Открывает и закрывает doc каждый раз
    чтобы не держать весь документ в памяти между вызовами."""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        raise ValueError(f"Не удалось открыть PDF: {e}") from e

    if doc.needs_pass:
        doc.close()
        raise ValueError("PDF защищён паролем — снимите защиту перед загрузкой")

    page = doc[page_idx]
    result = _process_page(page, page_idx + 1)
    doc.close()
    gc.collect()
    return result


def chunk_pdf_pages(pages: list[dict], pages_per_chunk: int = 8) -> list[str]:
    """Группирует страницы в текстовые чанки для передачи в Claude.

    C4: страницы с текстом < 20 символов пропускаются.
    Возвращает только непустые чанки (суммарный текст > 50 символов).
    """
    chunks: list[str] = []
    current_parts: list[str] = []
    current_text_len = 0

    for i, page_info in enumerate(pages):
        text = page_info["text"].strip()
        page_num = page_info["page"]
        method = page_info.get("method", "unknown")

        # C4: пропускаем страницы с менее чем 20 символами текста
        if len(text) < 20:
            continue

        header = f"--- Страница {page_num} (метод: {method}) ---"
        part = f"{header}\n{text}"
        current_parts.append(part)
        current_text_len += len(text)

        # Когда набрали pages_per_chunk страниц — закрываем чанк
        if len(current_parts) >= pages_per_chunk:
            chunk_text = "\n\n".join(current_parts)
            if current_text_len > 50:
                chunks.append(chunk_text)
            current_parts = []
            current_text_len = 0

    # Остаток страниц в последний чанк
    if current_parts and current_text_len > 50:
        chunks.append("\n\n".join(current_parts))

    return chunks
