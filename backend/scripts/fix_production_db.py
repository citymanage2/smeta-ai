"""
fix_production_db.py — one-shot idempotent repair for the 'stamp head' bug.

Problem:
  alembic_version was set to '006' via 'alembic stamp head' without running
  the actual migration SQL. As a result migrations 004–006 (projects table,
  tasks.project_id, estimation_status, cost, task_results.slot) never ran.
  'alembic upgrade head' now sees version 006 and does nothing.

Fix:
  1. If alembic_version > '003', reset it to '003' (the last version that
     was genuinely applied before the stamp).
  2. Exit — the 'alembic upgrade head' in startCommand then applies 004→006.

Idempotency:
  - If alembic_version is already '003' or lower: no-op (do not touch it).
  - If the alembic_version table does not exist: no-op (fresh DB — alembic
    will create it and run all migrations from scratch).
  - Migrations 004–006 use IF NOT EXISTS guards, so re-running them on a DB
    that already has the columns/tables is completely safe.

Usage (called automatically by render.yaml startCommand):
  python scripts/fix_production_db.py
"""
import asyncio
import os
import sys

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text


SAFE_VERSION = "003"   # last version known to be genuinely applied


async def fix_alembic_version(database_url: str) -> None:
    engine = create_async_engine(database_url, echo=False)

    try:
        async with engine.begin() as conn:
            # Check whether alembic_version table exists
            table_exists = await conn.scalar(
                text(
                    "SELECT EXISTS ("
                    "  SELECT 1 FROM information_schema.tables"
                    "  WHERE table_name = 'alembic_version'"
                    ")"
                )
            )

            if not table_exists:
                print(
                    "[fix_production_db] alembic_version table not found — "
                    "fresh database, nothing to fix."
                )
                return

            current = await conn.scalar(
                text("SELECT version_num FROM alembic_version LIMIT 1")
            )

            if current is None:
                print(
                    "[fix_production_db] alembic_version table is empty — "
                    "nothing to fix."
                )
                return

            if current <= SAFE_VERSION:
                print(
                    f"[fix_production_db] alembic_version is '{current}' "
                    f"(<= '{SAFE_VERSION}') — no reset needed."
                )
                return

            # Reset to safe version so upgrade head will re-apply 004→current
            await conn.execute(
                text(
                    "UPDATE alembic_version SET version_num = :v"
                ),
                {"v": SAFE_VERSION},
            )
            print(
                f"[fix_production_db] Reset alembic_version: "
                f"'{current}' → '{SAFE_VERSION}'. "
                f"'alembic upgrade head' will now re-apply missing migrations."
            )

    finally:
        await engine.dispose()


def main() -> None:
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        print(
            "[fix_production_db] DATABASE_URL not set — skipping.",
            file=sys.stderr,
        )
        sys.exit(0)

    asyncio.run(fix_alembic_version(database_url))


if __name__ == "__main__":
    main()
