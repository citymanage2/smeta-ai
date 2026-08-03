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

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Логика живёт в сервисе: её же вызывает админка. Здесь — только консольная
# обёртка, чтобы запуск из терминала остался запасным путём.
from app.services.estimate_migration import (  # noqa: E402
    STATUS_CONFLICT,
    STATUS_EMPTY,
    STATUS_IN_SYNC,
    STATUS_NEEDS_VERSION,
    STATUS_RESOLVED,
    _STATUS_LABEL,
    Entry,
    Report,
    migrate_estimates,
)

__all__ = [
    "migrate_estimates", "Report", "Entry",
    "STATUS_EMPTY", "STATUS_IN_SYNC", "STATUS_NEEDS_VERSION",
    "STATUS_CONFLICT", "STATUS_RESOLVED",
]


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
