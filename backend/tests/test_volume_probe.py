"""Фаза 2 ETA: объём работы меряется при создании задачи и не мешает её создать."""
import io
import uuid

import openpyxl
import pytest

from app.models.task import Task
from app.services import eta_service
from app.utils.volume_probe import (
    UNIT_ITEMS,
    UNIT_PAGES,
    UNIT_ROWS,
    probe_file_units,
    probe_files_units,
    probe_items_units,
)

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _xlsx_bytes(rows: int) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    for i in range(rows):
        ws.append([f"Позиция {i}", i, "шт"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _pdf_bytes(pages: int) -> bytes:
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page()
    data = doc.tobytes()
    doc.close()
    return data


def test_xlsx_rows_counted():
    units, kind = probe_file_units(XLSX_MIME, "grand.xlsx", _xlsx_bytes(37))
    assert kind == UNIT_ROWS
    assert units == 37


def test_pdf_pages_counted():
    units, kind = probe_file_units("application/pdf", "project.pdf", _pdf_bytes(5))
    assert kind == UNIT_PAGES
    assert units == 5


def test_image_counts_as_one_page():
    assert probe_file_units("image/png", "scan.png", b"\x89PNG") == (1, UNIT_PAGES)


def test_broken_file_yields_nothing_and_does_not_raise():
    assert probe_file_units(XLSX_MIME, "broken.xlsx", b"definitely not xlsx") == (None, None)
    assert probe_file_units("application/pdf", "broken.pdf", b"nope") == (None, None)


def test_unknown_format_yields_nothing():
    """XML-выгрузка Гранд-сметы: разметка не гарантирована — не гадаем."""
    assert probe_file_units("text/xml", "export.xml", b"<xml/>") == (None, None)


def test_empty_xlsx_is_not_zero_units():
    assert probe_file_units(XLSX_MIME, "empty.xlsx", _xlsx_bytes(0)) == (None, None)


def test_several_files_sum_within_dominant_unit():
    units, kind = probe_files_units([
        (XLSX_MIME, "a.xlsx", _xlsx_bytes(10)),
        (XLSX_MIME, "b.xlsx", _xlsx_bytes(15)),
        ("image/png", "scan.png", b"\x89PNG"),
    ])
    assert (units, kind) == (25, UNIT_ROWS)


def test_items_from_source_task():
    assert probe_items_units({"items": [{}, {}, {}]}) == (3, UNIT_ITEMS)
    assert probe_items_units({"items": []}) == (None, None)
    assert probe_items_units(None) == (None, None)


@pytest.mark.asyncio
async def test_measure_prefers_source_items_over_files(db_session):
    source = Task(
        id=str(uuid.uuid4()),
        user_role="user",
        task_type="LIST_FROM_GRAND",
        status="completed",
        input_files=[],
        input_file_data=[],
        chat_history=[],
        progress_data={"items": [{"name": f"п{i}"} for i in range(120)]},
    )
    db_session.add(source)
    await db_session.commit()

    units, kind = await eta_service.measure_task_volume(
        db_session,
        files=[(XLSX_MIME, "a.xlsx", _xlsx_bytes(9))],
        source_task_id=source.id,
    )
    assert (units, kind) == (120, UNIT_ITEMS)


@pytest.mark.asyncio
async def test_measure_falls_back_to_files_when_source_empty(db_session):
    units, kind = await eta_service.measure_task_volume(
        db_session,
        files=[(XLSX_MIME, "a.xlsx", _xlsx_bytes(9))],
        source_task_id=str(uuid.uuid4()),  # такой задачи нет
    )
    assert (units, kind) == (9, UNIT_ROWS)


@pytest.mark.asyncio
async def test_measure_without_anything_returns_none(db_session):
    assert await eta_service.measure_task_volume(db_session) == (None, None)
