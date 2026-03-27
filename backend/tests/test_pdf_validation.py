"""
Tests for PDF validation in pdf_to_content_block and its propagation
through the task processing pipeline.

Bug: Claude API returns "Error code: 400 - Could not process PDF" when fed
corrupted or empty PDF bytes. We must catch this before calling the API.

Validations added:
  1. File size > 32 MB  → ValueError("Файл слишком большой. Максимальный размер PDF: 32MB")
  2. Not a valid PDF    → ValueError("Файл не является валидным PDF")
"""
import base64
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from unittest.mock import AsyncMock, patch

from app.models.task import Task
from app.services.task_processor import TaskProcessor
from app.utils.file_parser import pdf_to_content_block


# ---------------------------------------------------------------------------
# Unit tests — pdf_to_content_block
# ---------------------------------------------------------------------------


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
    # 32 MB + 1 byte, with valid %PDF header so only size triggers
    big_pdf = b"%PDF-1.4" + b"\x00" * (32 * 1024 * 1024)
    with pytest.raises(ValueError, match="слишком большой"):
        pdf_to_content_block(big_pdf)


def test_pdf_to_content_block_accepts_valid_pdf():
    """A minimal valid PDF (starts with %PDF, within size limit) must succeed."""
    minimal = b"%PDF-1.4\n%%EOF"
    block = pdf_to_content_block(minimal)
    assert block["type"] == "document"
    assert block["source"]["media_type"] == "application/pdf"


# ---------------------------------------------------------------------------
# Integration tests — error propagates to task.error_message
# ---------------------------------------------------------------------------


def _make_research_task_with_pdf(pdf_bytes: bytes) -> Task:
    encoded = base64.b64encode(pdf_bytes).decode()
    return Task(
        id=str(uuid.uuid4()),
        user_role="user",
        task_type="RESEARCH_PROJECT",
        status="processing",
        input_files=[],
        input_file_data=[
            {"name": "project.pdf", "mime_type": "application/pdf", "content_b64": encoded}
        ],
        chat_history=[],
    )


@pytest_asyncio.fixture
async def corrupted_pdf_task(db_session):
    task = _make_research_task_with_pdf(b"not a pdf at all")
    db_session.add(task)
    await db_session.commit()
    return task


@pytest_asyncio.fixture
async def oversized_pdf_task(db_session):
    big_pdf = b"%PDF-1.4" + b"\x00" * (32 * 1024 * 1024)
    task = _make_research_task_with_pdf(big_pdf)
    db_session.add(task)
    await db_session.commit()
    return task


@pytest.mark.asyncio
async def test_corrupted_pdf_sets_task_failed(db_session, corrupted_pdf_task):
    """RESEARCH_PROJECT with a corrupted PDF must set status=failed with a human-readable error."""
    processor = TaskProcessor(corrupted_pdf_task.id, db_session)
    await processor.process()

    result = await db_session.execute(select(Task).where(Task.id == corrupted_pdf_task.id))
    task = result.scalar_one()

    assert task.status == "failed"
    assert task.error_message is not None
    assert "не является валидным PDF" in task.error_message


@pytest.mark.asyncio
async def test_oversized_pdf_sets_task_failed(db_session, oversized_pdf_task):
    """RESEARCH_PROJECT with a PDF > 32 MB must set status=failed with a human-readable error."""
    processor = TaskProcessor(oversized_pdf_task.id, db_session)
    await processor.process()

    result = await db_session.execute(select(Task).where(Task.id == oversized_pdf_task.id))
    task = result.scalar_one()

    assert task.status == "failed"
    assert task.error_message is not None
    assert "слишком большой" in task.error_message
