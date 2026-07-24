"""Тесты растеризации страниц для OCR (память/цвет).

Слой 1 фикса OCR-рестартов: страница рендерится в grayscale, чтобы срезать пик памяти
без потери точности Tesseract. Здесь проверяем именно рендер — без запуска tesseract,
поэтому тесты идут и там, где бинарь tesseract не установлен (нужен только pymupdf+Pillow).
"""
from __future__ import annotations

import pytest

fitz = pytest.importorskip("fitz")
pytest.importorskip("PIL")

from app.utils.pdf_ocr_extractor import _peak_rss_mb, _render_page_image


def _make_page(width: int = 300, height: int = 300):
    doc = fitz.open()
    page = doc.new_page(width=width, height=height)
    page.insert_text((20, 150), "Смета 123 руб.")
    return doc, page


def test_render_page_image_is_grayscale():
    """Рендер для OCR — одноканальный (mode 'L'): втрое меньше памяти, чем RGB."""
    doc, page = _make_page()
    try:
        img = _render_page_image(page)
        assert img.mode == "L"
        assert img.width > 0 and img.height > 0
    finally:
        doc.close()


def test_render_page_image_caps_width():
    """Очень широкая страница ограничивается 2480px по ширине (защита от гигантских pixmap)."""
    # A2 ~ 420мм → при 150 dpi это ~2480px и так; берём заведомо больше, чтобы сработал cap.
    doc, page = _make_page(width=4000, height=2000)
    try:
        img = _render_page_image(page)
        assert img.width <= 2480
    finally:
        doc.close()


def test_peak_rss_mb_positive():
    """Хелпер пикового RSS возвращает разумное положительное число МБ."""
    val = _peak_rss_mb()
    assert isinstance(val, int)
    assert 1 <= val < 100_000
