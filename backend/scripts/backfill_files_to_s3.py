"""backfill_files_to_s3.py — перенос файлов из PostgreSQL BLOB в S3 (Phase 4).

⚠️ OBSOLETE после миграции 035 (contract-фаза). Скрипт обращается к BLOB-колонкам
task_input_files.content / task_results.file_data, которые дропнуты миграцией 035.
Backfill на проде завершён (остаток 0/0). Файл оставлен как audit-trail процесса
переноса; приложением не импортируется. Запускать после 035 нельзя — упадёт на
отсутствующих колонках.


Идёт батчами по task_input_files и task_results (content/file_data IS NOT NULL,
storage_key IS NULL): грузит байты в S3, проставляет storage_key, обнуляет BLOB.
Отдельно обрабатывает legacy tasks.input_file_data (base64 в JSON). Идемпотентный —
повторный запуск пропускает уже перенесённые строки.

Перенос идёт НЕЗАВИСИМО от S3_ENABLED (это сама миграция). После него строки
читаются из S3 через dual-read даже при S3_ENABLED=False.

Запуск (из backend/, с прод-DATABASE_URL и S3-кредами в окружении):
    python scripts/backfill_files_to_s3.py --dry-run    # только показать объёмы
    python scripts/backfill_files_to_s3.py              # перенос + верификация (re-read)
    python scripts/backfill_files_to_s3.py --no-verify  # без сверки (быстрее)

Порядок деплоя: сначала выкатить dual-read/new-write код (Phase 3) туда, где идёт
backfill, ИНАЧЕ старый код, не знающий про storage_key, сломается на обнулённых BLOB.
"""
import argparse
import asyncio
import base64
import os
import sys

from sqlalchemy import select, func
from sqlalchemy.orm.attributes import flag_modified

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings  # noqa: E402
from app.database import AsyncSessionLocal  # noqa: E402
from app.models.task import Task  # noqa: E402
from app.models.task_input_file import TaskInputFile  # noqa: E402
from app.models.result import TaskResult  # noqa: E402
from app.services import storage_service  # noqa: E402

BATCH = 50


def _input_key(r: TaskInputFile) -> str:
    return storage_service.build_input_key(r.task_id, r.file_index, r.file_name)


def _result_key(r: TaskResult) -> str:
    return storage_service.build_result_key(r.task_id, r.slot, r.file_name)


async def _count_pending(session_factory, model, blob_attr: str) -> int:
    blob_col = getattr(model, blob_attr)
    async with session_factory() as db:
        n = (
            await db.execute(
                select(func.count())
                .select_from(model)
                .where(blob_col.isnot(None), model.storage_key.is_(None))
            )
        ).scalar()
    return n or 0


async def backfill_table(
    model, blob_attr, key_builder, *, dry_run, verify, session_factory=AsyncSessionLocal
) -> tuple[int, int]:
    """Перенести BLOB одной таблицы в S3. Возвращает (было_к_переносу, перенесено)."""
    blob_col = getattr(model, blob_attr)
    pending = await _count_pending(session_factory, model, blob_attr)
    print(f"[{model.__tablename__}] к переносу: {pending}")
    if dry_run or pending == 0:
        return pending, 0

    migrated = 0
    while True:
        async with session_factory() as db:
            rows = (
                await db.execute(
                    select(model)
                    .where(blob_col.isnot(None), model.storage_key.is_(None))
                    .limit(BATCH)
                )
            ).scalars().all()
            if not rows:
                break
            for r in rows:
                blob = getattr(r, blob_attr)
                key = key_builder(r)
                await storage_service.put_object(key, blob, getattr(r, "mime_type", None))
                if verify and await storage_service.get_object(key) != blob:
                    print(f"  ВЕРИФИКАЦИЯ НЕ ПРОШЛА {key} (id={r.id}) — BLOB оставлен")
                    continue
                r.storage_key = key
                setattr(r, blob_attr, None)
                migrated += 1
            await db.commit()
            print(f"  [{model.__tablename__}] перенесено {migrated}/{pending}")
    return pending, migrated


async def backfill_legacy_json(*, dry_run, verify, session_factory=AsyncSessionLocal) -> tuple[int, int]:
    """Legacy: tasks.input_file_data с content_b64 → S3 + строки task_input_files."""
    async with session_factory() as db:
        tasks = (
            await db.execute(select(Task).where(Task.input_file_data.isnot(None)))
        ).scalars().all()
        task_ids = [
            t.id
            for t in tasks
            if any(isinstance(f, dict) and f.get("content_b64") for f in (t.input_file_data or []))
        ]
    print(f"[legacy input_file_data] задач с байтами в JSON: {len(task_ids)}")
    if dry_run or not task_ids:
        return len(task_ids), 0

    migrated = 0
    for tid in task_ids:
        async with session_factory() as db:
            task = await db.get(Task, tid)
            if task is None:
                continue
            new_meta = []
            for idx, f in enumerate(list(task.input_file_data or [])):
                b64 = f.get("content_b64") if isinstance(f, dict) else None
                if not b64:
                    new_meta.append(f)
                    continue
                raw = base64.b64decode(b64)
                key = storage_service.build_input_key(tid, idx, f.get("name", "file"))
                await storage_service.put_object(key, raw, f.get("mime_type"))
                if verify and await storage_service.get_object(key) != raw:
                    print(f"  ВЕРИФИКАЦИЯ НЕ ПРОШЛА {key} (задача {tid} idx {idx}) — оставлен JSON")
                    new_meta.append(f)
                    continue
                existing = (
                    await db.execute(
                        select(TaskInputFile).where(
                            TaskInputFile.task_id == tid, TaskInputFile.file_index == idx
                        )
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    existing.storage_key = key
                    existing.content = None
                else:
                    db.add(
                        TaskInputFile(
                            task_id=tid,
                            file_index=idx,
                            file_name=f.get("name", "file"),
                            mime_type=f.get("mime_type", "application/octet-stream"),
                            size_bytes=int(f.get("size_bytes") or len(raw)),
                            storage_key=key,
                            content=None,
                        )
                    )
                new_meta.append({k: v for k, v in f.items() if k != "content_b64"})
            task.input_file_data = new_meta
            flag_modified(task, "input_file_data")
            await db.commit()
            migrated += 1
    return len(task_ids), migrated


async def run(dry_run: bool, verify: bool, session_factory=AsyncSessionLocal) -> int:
    mode = "DRY-RUN" if dry_run else ("LIVE+VERIFY" if verify else "LIVE")
    print(f"=== Backfill файлов → S3 [{mode}] bucket={settings.S3_BUCKET or '—'} ===")
    if not dry_run and not settings.S3_BUCKET:
        print("ОШИБКА: S3_BUCKET не задан — перенос невозможен.")
        return 1

    await backfill_table(
        TaskInputFile, "content", _input_key, dry_run=dry_run, verify=verify, session_factory=session_factory
    )
    await backfill_table(
        TaskResult, "file_data", _result_key, dry_run=dry_run, verify=verify, session_factory=session_factory
    )
    await backfill_legacy_json(dry_run=dry_run, verify=verify, session_factory=session_factory)

    left_i = await _count_pending(session_factory, TaskInputFile, "content")
    left_r = await _count_pending(session_factory, TaskResult, "file_data")
    print(f"=== Остаток BLOB без storage_key: input={left_i}, result={left_r} ===")
    if not dry_run and (left_i or left_r):
        print("ВНИМАНИЕ: остались неперенесённые строки (см. ошибки верификации выше).")
        return 2
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description="Backfill файлов из PostgreSQL BLOB в S3")
    p.add_argument("--dry-run", action="store_true", help="только показать объёмы, без записи")
    p.add_argument("--no-verify", action="store_true", help="не перечитывать объект из S3 для сверки")
    args = p.parse_args()
    code = asyncio.run(run(args.dry_run, verify=not args.no_verify))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
