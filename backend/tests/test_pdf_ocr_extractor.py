"""Тесты растеризации страниц для OCR (память/цвет).

Слой 1 фикса OCR-рестартов: страница рендерится в grayscale, чтобы срезать пик памяти
без потери точности Tesseract. Здесь проверяем именно рендер — без запуска tesseract,
поэтому тесты идут и там, где бинарь tesseract не установлен (нужен только pymupdf+Pillow).
"""
from __future__ import annotations

import pytest

fitz = pytest.importorskip("fitz")
pytest.importorskip("PIL")

from app.utils.pdf_ocr_extractor import (
    _peak_rss_mb,
    _render_page_image,
    timed_out_page_numbers,
)


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


def test_timed_out_page_numbers():
    """Собирает номера страниц с флагом ocr_timeout (текст потерян → перечень неполон)."""
    pages = [
        {"page": 1, "text": "ok", "method": "ocr"},
        {"page": 2, "text": "", "method": "ocr", "ocr_timeout": True},
        {"page": 3, "text": "ok", "method": "embedded"},
        {"page": 4, "text": "", "method": "ocr", "ocr_timeout": True},
    ]
    assert timed_out_page_numbers(pages) == [2, 4]
    assert timed_out_page_numbers([]) == []


def test_ocr_page_tags_timeout(monkeypatch):
    """Таймаут Tesseract помечает страницу ocr_timeout=True, а не теряет её молча."""
    pytest.importorskip("pytesseract")
    import app.utils.pdf_ocr_extractor as ex

    monkeypatch.setattr(ex, "_TESSERACT_AVAILABLE", True)

    def _boom(*args, **kwargs):
        raise RuntimeError("timeout")

    monkeypatch.setattr(ex.pytesseract, "image_to_string", _boom)

    doc, page = _make_page()
    try:
        res = ex._ocr_page(page, 3)
        assert res["ocr_timeout"] is True
        assert res["text"] == ""
        assert res["page"] == 3
    finally:
        doc.close()
