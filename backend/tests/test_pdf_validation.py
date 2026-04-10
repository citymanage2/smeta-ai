"""
Tests for PDF validation in pdf_to_content_block.

Validations:
  1. File size > 32 MB  → ValueError("Файл слишком большой. Максимальный размер PDF: 32MB")
  2. Not a valid PDF    → ValueError("Файл не является валидным PDF")
"""
import pytest

from app.utils.file_parser import pdf_to_content_block


def test_pdf_to_content_block_rejects_empty_bytes():
    """Empty bytes are not a valid PDF."""
    with pytest.raises(ValueError, match="не является валидным PDF"):
        pdf_to_content_block(b"")


def test_pdf_to_content_block_rejects_corrupted_bytes():
    """Bytes that don't start with %PDF are not a valid PDF."""
    with pytest.raises(ValueError, match="не является валидным PDF"):
        pdf_to_content_block(b"PK\x03\x04corrupted data here")


def test_pdf_to_content_block_rejects_oversized_pdf():
    """PDF larger than 32 MB must be rejected before base64-encoding."""
    big_pdf = b"%PDF-1.4" + b"\x00" * (32 * 1024 * 1024)
    with pytest.raises(ValueError, match="слишком большой"):
        pdf_to_content_block(big_pdf)


def test_pdf_to_content_block_accepts_valid_pdf():
    """A minimal valid PDF (starts with %PDF, within size limit) must succeed."""
    minimal = b"%PDF-1.4\n%%EOF"
    block = pdf_to_content_block(minimal)
    assert block["type"] == "document"
    assert block["source"]["media_type"] == "application/pdf"
