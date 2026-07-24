"""Тесты storage_service: put/get/delete/exists/prefix на in-memory fake S3 + ключи."""
import io
import pytest
from botocore.exceptions import ClientError

from app.services import storage_service as ss

pytestmark = pytest.mark.asyncio


class _FakeS3:
    """Минимальный in-memory S3-клиент (только используемые операции)."""

    def __init__(self):
        self.store: dict[str, bytes] = {}

    def put_object(self, Bucket, Key, Body, **kw):
        self.store[Key] = Body
        return {}

    def get_object(self, Bucket, Key):
        if Key not in self.store:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": io.BytesIO(self.store[Key])}

    def delete_object(self, Bucket, Key):
        self.store.pop(Key, None)
        return {}

    def head_object(self, Bucket, Key):
        if Key not in self.store:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        return {}

    def list_objects_v2(self, Bucket, Prefix, ContinuationToken=None):
        keys = [k for k in self.store if k.startswith(Prefix)]
        return {"Contents": [{"Key": k} for k in keys], "IsTruncated": False}

    def delete_objects(self, Bucket, Delete):
        for o in Delete["Objects"]:
            self.store.pop(o["Key"], None)
        return {}


@pytest.fixture
def fake(monkeypatch):
    client = _FakeS3()
    monkeypatch.setattr(ss, "_client", client)
    return client


async def test_put_get_roundtrip(fake):
    await ss.put_object("tasks/t1/input/0-a.pdf", b"hello", "application/pdf")
    assert await ss.get_object("tasks/t1/input/0-a.pdf") == b"hello"


async def test_get_missing_raises_storage_error(fake):
    with pytest.raises(ss.StorageError):
        await ss.get_object("does/not/exist")


async def test_object_exists(fake):
    assert await ss.object_exists("k") is False
    await ss.put_object("k", b"x")
    assert await ss.object_exists("k") is True


async def test_delete_object_idempotent(fake):
    await ss.put_object("k", b"x")
    await ss.delete_object("k")
    assert await ss.object_exists("k") is False
    await ss.delete_object("k")  # повторное удаление — не ошибка


async def test_delete_prefix_removes_only_matching(fake):
    await ss.put_object("tasks/t1/input/0-a", b"1")
    await ss.put_object("tasks/t1/result/estimate-b", b"2")
    await ss.put_object("tasks/t2/input/0-c", b"3")

    n = await ss.delete_prefix("tasks/t1/")
    assert n == 2
    assert await ss.object_exists("tasks/t1/input/0-a") is False
    assert await ss.object_exists("tasks/t2/input/0-c") is True  # чужой префикс цел


async def test_store_input_file_s3_enabled(fake, monkeypatch):
    monkeypatch.setattr(ss.settings, "S3_ENABLED", True)
    key, content = await ss.store_input_file("t1", 0, "a.pdf", "application/pdf", b"hi")
    assert content is None
    assert key and key.startswith("tasks/t1/input/0-")
    assert await ss.get_object(key) == b"hi"  # реально легло в S3


async def test_store_input_file_s3_disabled(fake, monkeypatch):
    monkeypatch.setattr(ss.settings, "S3_ENABLED", False)
    key, content = await ss.store_input_file("t1", 0, "a.pdf", "application/pdf", b"hi")
    assert key is None and content == b"hi"  # старый путь: BLOB в БД


async def test_store_result_file_s3_enabled(fake, monkeypatch):
    monkeypatch.setattr(ss.settings, "S3_ENABLED", True)
    key, data = await ss.store_result_file("t1", "estimate", "e.xlsx", "x", b"bytes")
    assert data is None
    assert key.startswith("tasks/t1/result/estimate-")
    assert await ss.get_object(key) == b"bytes"


async def test_load_bytes_dual_read(fake):
    await ss.put_object("k1", b"from_s3")
    assert await ss.load_bytes("k1", None) == b"from_s3"        # storage_key → S3
    assert await ss.load_bytes(None, b"from_blob") == b"from_blob"  # только BLOB
    assert await ss.load_bytes("k1", b"ignored") == b"from_s3"  # приоритет ключа
    with pytest.raises(ss.StorageError):
        await ss.load_bytes(None, None)                          # ничего → ошибка


async def test_key_builders_and_sanitize():
    # path traversal в имени не уводит из префикса задачи; в ключе есть uuid-токен
    ik = ss.build_input_key("t1", 0, "../../etc/passwd")
    assert ik.startswith("tasks/t1/input/0-") and ik.endswith("-passwd")
    assert ss.build_result_key("t1", "estimate", "Смета v2.xlsx").startswith(
        "tasks/t1/result/estimate-"
    )
    # два вызова → разные ключи (уникальность объектов, нет перезаписи при архивации)
    assert ss.build_result_key("t1", "optimized", "o.xlsx") != ss.build_result_key(
        "t1", "optimized", "o.xlsx"
    )
    assert ss.sanitize_filename("") == "file"
    assert "/" not in ss.sanitize_filename("a/b\\c.pdf")
    assert ss.task_prefix("t1") == "tasks/t1/"
