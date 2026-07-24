"""Тест backfill-скрипта: перенос BLOB → S3, обнуление content, идемпотентность."""
import io
import uuid

import pytest
from botocore.exceptions import ClientError
from sqlalchemy import select

from app.models.task import Task
from app.models.task_input_file import TaskInputFile
from app.services import storage_service as ss
from scripts.backfill_files_to_s3 import run
from tests.conftest import TestSessionLocal

pytestmark = pytest.mark.asyncio


class _FakeS3:
    def __init__(self):
        self.store = {}

    def put_object(self, Bucket, Key, Body, **kw):
        self.store[Key] = Body
        return {}

    def get_object(self, Bucket, Key):
        if Key not in self.store:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": io.BytesIO(self.store[Key])}


@pytest.fixture
def fake_s3(monkeypatch):
    client = _FakeS3()
    monkeypatch.setattr(ss, "_client", client)
    monkeypatch.setattr(ss.settings, "S3_BUCKET", "test-bucket")
    return client


async def _seed_input_file(db, content=b"abc") -> str:
    tid = str(uuid.uuid4())
    db.add(Task(
        id=tid, user_role="user", task_type="LIST_FROM_GRAND", status="completed",
        input_files=[], input_file_data=[], chat_history=[],
    ))
    db.add(TaskInputFile(
        task_id=tid, file_index=0, file_name="a.pdf",
        mime_type="application/pdf", size_bytes=len(content), content=content,
    ))
    await db.commit()
    return tid


async def test_backfill_migrates_and_is_idempotent(db_session, fake_s3):
    tid = await _seed_input_file(db_session, b"abc")

    code = await run(dry_run=False, verify=True, session_factory=TestSessionLocal)
    assert code == 0

    db_session.expire_all()
    row = (
        await db_session.execute(select(TaskInputFile).where(TaskInputFile.task_id == tid))
    ).scalar_one()
    assert row.storage_key is not None      # ключ проставлен
    assert row.content is None               # BLOB обнулён
    assert fake_s3.store[row.storage_key] == b"abc"  # байты реально в S3

    key_before = row.storage_key
    # повторный запуск: строка уже перенесена → ничего не делает, ключ не меняется
    code2 = await run(dry_run=False, verify=True, session_factory=TestSessionLocal)
    assert code2 == 0
    db_session.expire_all()
    row2 = (
        await db_session.execute(select(TaskInputFile).where(TaskInputFile.task_id == tid))
    ).scalar_one()
    assert row2.storage_key == key_before


async def test_backfill_dry_run_changes_nothing(db_session, fake_s3):
    tid = await _seed_input_file(db_session, b"xyz")

    code = await run(dry_run=True, verify=False, session_factory=TestSessionLocal)
    assert code == 0

    db_session.expire_all()
    row = (
        await db_session.execute(select(TaskInputFile).where(TaskInputFile.task_id == tid))
    ).scalar_one()
    assert row.storage_key is None           # dry-run не трогает БД
    assert row.content == b"xyz"
    assert fake_s3.store == {}               # и не пишет в S3
