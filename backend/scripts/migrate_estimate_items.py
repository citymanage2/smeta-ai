"""
migrate_estimate_items.py — разовый перевод смет на единый источник правды.

До Фазы 5 смета жила в двух местах: `task.progress_data['items']` (что выдал
расчёт) и `EstimateVersion.rows` (что видит редактор). Они молча расходились.
Правда теперь одна — рабочая версия сметы. Этот скрипт создаёт её тем сметам,
у которых её ещё нет, и показывает те, где два хранилища разошлись.

**Единственное необратимое действие во всём плане.** Поэтому:

  * по умолчанию — только отчёт, ничего не меняется;
  * смета с расхождением НЕ мигрируется автоматически: она попадает в отчёт и
    ждёт решения человека;
  * повторный запуск ничего не делает — миграция идемпотентна;
  * перед перезаписью строк обе стороны целиком сохраняются в историю задачи.

Использование:

    cd backend

    # 1. Отчёт — обязательный первый шаг, ничего не меняет
    DATABASE_URL=postgresql+asyncpg://... python scripts/migrate_estimate_items.py

    # 2. Создать недостающие версии; сметы с расхождением пропустить
    DATABASE_URL=... python scripts/migrate_estimate_items.py --apply

    # 3. Разобрать расхождения, выбрав сторону-победителя
    DATABASE_URL=... python scripts/migrate_estimate_items.py --apply --prefer=items

    # Активные тендеры не трогать
    DATABASE_URL=... python scripts/migrate_estimate_items.py --apply \
        --exclude 11111111-2222-... --exclude 33333333-...
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid as _uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models.history import TaskHistory  # noqa: E402
from app.models.task import Task  # noqa: E402
from app.services import estimate_store  # noqa: E402
from app.utils.estimate_rows import (  # noqa: E402
    items_signature,
    items_to_rows,
    items_total,
    rows_to_items,
)

ESTIMATE_TASK_TYPE = "ESTIMATE_FROM_LIST"

# Что случилось с каждой сметой.
STATUS_EMPTY = "empty"                    # позиций нет — мигрировать нечего
STATUS_EXCLUDED = "excluded"              # задача в списке исключений
STATUS_NEEDS_VERSION = "needs_version"    # версии нет, создаётся из позиций
STATUS_IN_SYNC = "in_sync"                # оба хранилища совпадают
STATUS_CONFLICT = "conflict"              # разошлись, решает человек
STATUS_RESOLVED = "resolved"              # расхождение разобрано по --prefer

_STATUS_LABEL = {
    STATUS_EMPTY: "нет позиций",
    STATUS_EXCLUDED: "исключена",
    STATUS_NEEDS_VERSION: "нужна версия",
    STATUS_IN_SYNC: "совпадает",
    STATUS_CONFLICT: "РАСХОЖДЕНИЕ",
    STATUS_RESOLVED: "расхождение разобрано",
}


@dataclass
class Entry:
    task_id: str
    task_name: str
    status: str
    items_count: int = 0
    version_count: int = 0
    diff_count: int = 0
    items_total: float = 0.0
    version_total: float = 0.0


@dataclass
class Report:
    entries: list = field(default_factory=list)
    counts: dict = field(default_factory=dict)
    applied: bool = False

    def add(self, entry: Entry) -> None:
        self.entries.append(entry)
        self.counts[entry.status] = self.counts.get(entry.status, 0) + 1


def _diff_count(left: list, right: list) -> int:
    """Сколько позиций расходится между двумя копиями сметы."""
    a, b = items_signature(left), items_signature(right)
    if len(a) != len(b):
        return max(len(a), len(b)) - min(len(a), len(b)) + sum(
            1 for x, y in zip(a, b) if x != y
        )
    return sum(1 for x, y in zip(a, b) if x != y)


async def _backup(db: AsyncSession, task: Task, rows: list, items: list) -> None:
    """Сохранить обе стороны целиком — единственный способ вернуться назад."""
    db.add(TaskHistory(
        id=str(_uuid.uuid4()),
        task_id=str(task.id),
        operation_type="estimate_migration",
        slot=estimate_store.ESTIMATE_SLOT,
        description=(
            "Перевод сметы на единый источник правды: строки версии заменены "
            "позициями расчёта. Обе стороны сохранены здесь."
        ),
        previous_value={"rows": rows, "items": items},
        new_value={"migrated_at": datetime.now(timezone.utc).isoformat()},
        document_kind="estimate",
    ))


async def migrate_estimates(
    db: AsyncSession,
    *,
    apply: bool = False,
    exclude: Optional[set] = None,
    prefer: Optional[str] = None,
) -> Report:
    """Пройти по всем сметам. Без `apply=True` не меняет ничего.

    `prefer` разбирает расхождения: `items` — победили позиции расчёта,
    `version` — победили строки редактора (версия и так правда, действий нет).
    Без него смета с расхождением остаётся нетронутой.
    """
    exclude = {str(x) for x in (exclude or set())}
    report = Report(applied=apply)

    res = await db.execute(
        select(Task).where(Task.task_type == ESTIMATE_TASK_TYPE).order_by(Task.created_at)
    )
    for task in res.scalars().all():
        task_id = str(task.id)
        name = task.name or "(без названия)"

        if task_id in exclude:
            report.add(Entry(task_id, name, STATUS_EXCLUDED))
            continue

        items = list((task.progress_data or {}).get("items") or [])
        version = await estimate_store.get_working_version(db, task_id)
        version_items = rows_to_items(version.rows) if version is not None else []

        if not items and version is None:
            report.add(Entry(task_id, name, STATUS_EMPTY))
            continue

        if version is None:
            entry = Entry(
                task_id, name, STATUS_NEEDS_VERSION,
                items_count=len(items), items_total=items_total(items),
            )
            if apply:
                await estimate_store.ensure_working_version(
                    db, task, items_to_rows(items), commit=False,
                )
            report.add(entry)
            continue

        if not items or items_signature(items) == items_signature(version_items):
            report.add(Entry(
                task_id, name, STATUS_IN_SYNC,
                items_count=len(items), version_count=len(version_items),
                items_total=items_total(items),
                version_total=items_total(version_items),
            ))
            continue

        entry = Entry(
            task_id, name, STATUS_CONFLICT,
            items_count=len(items), version_count=len(version_items),
            diff_count=_diff_count(items, version_items),
            items_total=items_total(items), version_total=items_total(version_items),
        )

        if apply and prefer == "items":
            await _backup(db, task, list(version.rows or []), items)
            await estimate_store.write_rows(db, task, items_to_rows(items), commit=False)
            entry.status = STATUS_RESOLVED
        elif apply and prefer == "version":
            # Версия уже является источником правды — записывать нечего.
            entry.status = STATUS_RESOLVED

        report.add(entry)

    if apply:
        await db.commit()
    return report


def print_report(report: Report) -> None:
    header = "ПРИМЕНЕНО" if report.applied else "ОТЧЁТ (ничего не изменено)"
    print(f"\n=== Перевод смет на единый источник правды — {header} ===\n")

    for entry in report.entries:
        if entry.status in (STATUS_EMPTY, STATUS_IN_SYNC):
            continue
        line = f"[{_STATUS_LABEL[entry.status]:>22}]  {entry.task_id}  {entry.task_name}"
        if entry.status in (STATUS_CONFLICT, STATUS_RESOLVED):
            line += (
                f"\n{'':26}  расходится позиций: {entry.diff_count};"
                f" итог расчёта {entry.items_total:,.2f} ₽,"
                f" итог редактора {entry.version_total:,.2f} ₽"
            )
        elif entry.status == STATUS_NEEDS_VERSION:
            line += f"\n{'':26}  позиций: {entry.items_count}, итог {entry.items_total:,.2f} ₽"
        print(line)

    print("\n--- Итого ---")
    for status, label in _STATUS_LABEL.items():
        count = report.counts.get(status, 0)
        if count:
            print(f"  {label}: {count}")

    conflicts = report.counts.get(STATUS_CONFLICT, 0)
    if conflicts:
        print(
            f"\n  ВНИМАНИЕ: {conflicts} смет(ы) с расхождением НЕ мигрированы.\n"
            "  Разберите их вручную или запустите с --prefer=items / --prefer=version."
        )
    print()


async def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="применить изменения (без флага — только отчёт)")
    parser.add_argument("--prefer", choices=["items", "version"], default=None,
                        help="чью сторону считать верной при расхождении")
    parser.add_argument("--exclude", action="append", default=[],
                        help="идентификатор задачи, которую не трогать (можно несколько)")
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("Не задан DATABASE_URL")
        sys.exit(1)

    engine = create_async_engine(database_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        report = await migrate_estimates(
            session, apply=args.apply,
            exclude=set(args.exclude), prefer=args.prefer,
        )
    await engine.dispose()
    print_report(report)


if __name__ == "__main__":
    asyncio.run(_main())
