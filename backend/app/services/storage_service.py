"""S3-хранилище файлов (Timeweb Cloud Storage, S3-совместимое).

Единая абстракция над boto3: роуты и task_processor работают с этими функциями,
не зная про boto3. Даёт одну точку конфигурации/ретраев, лёгкую подмену в тестах
(мок-клиент) и возможность позже добавить presigned URL без правок вызывающих.

boto3 синхронный — блокирующие вызовы обёрнуты в run_in_threadpool (файловые
операции редкие, не hot-path, overhead потока незначим).

Схема ключей:
    tasks/{task_id}/input/{file_index}-{sanitized_name}
    tasks/{task_id}/result/{slot}-{sanitized_name}
Префикс по task_id → каскадное удаление всех объектов задачи одним delete_prefix.
"""
from __future__ import annotations

import re
import uuid
from typing import Optional

import structlog
from starlette.concurrency import run_in_threadpool

from app.config import settings

logger = structlog.get_logger()


class StorageError(Exception):
    """Доменная ошибка хранилища (обёртка над botocore ClientError и пр.)."""


# Ленивая инициализация клиента: не требуем креды при импорте, легко подменить в тестах.
_client = None


def _get_client():
    global _client
    if _client is None:
        import boto3
        from botocore.config import Config

        _client = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL,
            region_name=settings.S3_REGION,
            aws_access_key_id=settings.S3_ACCESS_KEY_ID,
            aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY,
            config=Config(
                signature_version="s3v4",
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )
    return _client


# ---------------------------------------------------------------------------
# Ключи
# ---------------------------------------------------------------------------

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_filename(name: str) -> str:
    """Безопасная метка имени для ключа: без разделителей путей и спецсимволов.

    Имя файла в ключе — только человекочитаемая метка; сам путь строится из
    task_id + index/slot, поэтому имя не может увести объект в чужой префикс
    (защита от path traversal). Пустое имя → 'file'.
    """
    name = (name or "").replace("\\", "/").split("/")[-1]  # отбросить путь
    name = _SAFE.sub("_", name).strip("._")
    return name[:120] or "file"


def _token() -> str:
    """Короткий уникальный токен в ключе — чтобы новый объект НИКОГДА не перезаписал
    старый при переиспользовании слота (архивация optimized→optimized_vN, пересохранение
    estimate). Каждая запись = отдельный объект; ключ хранится в БД, не реконструируется."""
    return uuid.uuid4().hex[:8]


def build_input_key(task_id: str, file_index: int, filename: str) -> str:
    return f"tasks/{task_id}/input/{file_index}-{_token()}-{sanitize_filename(filename)}"


def build_result_key(task_id: str, slot: str, filename: str) -> str:
    slot = _SAFE.sub("_", slot or "result")
    return f"tasks/{task_id}/result/{slot}-{_token()}-{sanitize_filename(filename)}"


def task_prefix(task_id: str) -> str:
    return f"tasks/{task_id}/"


# ---------------------------------------------------------------------------
# Операции (async-обёртки)
# ---------------------------------------------------------------------------

async def put_object(key: str, data: bytes, content_type: Optional[str] = None) -> None:
    """Записать объект. Бросает StorageError при сбое."""
    kwargs = {"Bucket": settings.S3_BUCKET, "Key": key, "Body": data}
    if content_type:
        kwargs["ContentType"] = content_type
    try:
        await run_in_threadpool(lambda: _get_client().put_object(**kwargs))
    except Exception as e:  # noqa: BLE001 — оборачиваем в доменную ошибку
        logger.error("S3 put failed", key=key, error=str(e))
        raise StorageError(f"put_object failed for {key}: {e}") from e


async def get_object(key: str) -> bytes:
    """Прочитать объект целиком. Бросает StorageError, если объекта нет/сбой.

    Файлы ограничены MAX_FILE_SIZE_MB (десятки МБ) — читаем в память целиком,
    как это делалось с BLOB. Потоковую отдачу можно добавить позже без правок
    вызывающего кода.
    """
    def _read() -> bytes:
        resp = _get_client().get_object(Bucket=settings.S3_BUCKET, Key=key)
        return resp["Body"].read()

    try:
        return await run_in_threadpool(_read)
    except Exception as e:  # noqa: BLE001
        logger.error("S3 get failed", key=key, error=str(e))
        raise StorageError(f"get_object failed for {key}: {e}") from e


async def delete_object(key: str) -> None:
    """Удалить один объект (идемпотентно: отсутствие объекта — не ошибка)."""
    try:
        await run_in_threadpool(
            lambda: _get_client().delete_object(Bucket=settings.S3_BUCKET, Key=key)
        )
    except Exception as e:  # noqa: BLE001
        logger.error("S3 delete failed", key=key, error=str(e))
        raise StorageError(f"delete_object failed for {key}: {e}") from e


async def delete_prefix(prefix: str) -> int:
    """Удалить все объекты под префиксом (list + batch delete). Вернуть число.

    Для каскадной очистки всех файлов задачи (`tasks/{task_id}/`). Пагинация +
    удаление батчами по 1000 (лимит S3 DeleteObjects).
    """
    def _delete_all() -> int:
        client = _get_client()
        bucket = settings.S3_BUCKET
        deleted = 0
        token = None
        while True:
            kw = {"Bucket": bucket, "Prefix": prefix}
            if token:
                kw["ContinuationToken"] = token
            resp = client.list_objects_v2(**kw)
            objs = [{"Key": o["Key"]} for o in resp.get("Contents", [])]
            for i in range(0, len(objs), 1000):
                batch = objs[i : i + 1000]
                client.delete_objects(Bucket=bucket, Delete={"Objects": batch})
                deleted += len(batch)
            if resp.get("IsTruncated"):
                token = resp.get("NextContinuationToken")
            else:
                break
        return deleted

    try:
        n = await run_in_threadpool(_delete_all)
        if n:
            logger.info("S3 prefix deleted", prefix=prefix, count=n)
        return n
    except Exception as e:  # noqa: BLE001
        logger.error("S3 delete_prefix failed", prefix=prefix, error=str(e))
        raise StorageError(f"delete_prefix failed for {prefix}: {e}") from e


async def store_input_file(
    task_id: str, file_index: int, filename: str, mime_type: Optional[str], data: bytes
) -> tuple[Optional[str], Optional[bytes]]:
    """Куда положить байты входного файла → вернуть (storage_key, content) для строки.

    S3_ENABLED → пишем в S3, возвращаем (key, None). Иначе (None, data) — старый
    путь (BLOB в БД). Вызывающий проставляет оба поля в TaskInputFile.
    """
    if settings.S3_ENABLED:
        key = build_input_key(task_id, file_index, filename)
        await put_object(key, data, mime_type)
        return key, None
    return None, data


async def store_result_file(
    task_id: str, slot: str, filename: str, mime_type: Optional[str], data: bytes
) -> tuple[Optional[str], Optional[bytes]]:
    """Куда положить байты результата → вернуть (storage_key, file_data) для строки."""
    if settings.S3_ENABLED:
        key = build_result_key(task_id, slot, filename)
        await put_object(key, data, mime_type)
        return key, None
    return None, data


async def load_bytes(storage_key: Optional[str], blob: Optional[bytes]) -> bytes:
    """Dual-read: storage_key задан → из S3; иначе BLOB; иначе StorageError.

    Единый путь чтения для роутов и task_processor на переходный период
    (смешанные данные: часть в S3, часть ещё в БД).
    """
    if storage_key:
        return await get_object(storage_key)
    if blob is not None:
        return blob
    raise StorageError("нет содержимого: ни storage_key, ни BLOB")


async def object_exists(key: str) -> bool:
    """Есть ли объект (head_object). 404 → False, иные ошибки → StorageError."""
    def _head() -> bool:
        from botocore.exceptions import ClientError

        try:
            _get_client().head_object(Bucket=settings.S3_BUCKET, Key=key)
            return True
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in ("404", "NoSuchKey", "NotFound"):
                return False
            raise

    try:
        return await run_in_threadpool(_head)
    except Exception as e:  # noqa: BLE001
        logger.error("S3 head failed", key=key, error=str(e))
        raise StorageError(f"object_exists failed for {key}: {e}") from e
