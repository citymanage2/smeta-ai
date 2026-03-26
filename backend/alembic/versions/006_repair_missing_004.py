"""Repair missing 004 migration (projects table + task columns + slot)

Revision ID: 006
Revises: 005
Create Date: 2026-03-26 00:00:00.000000

Context: production DB was stamped to 005 without running 004, so
projects table and several columns are missing. This migration is
fully idempotent — every operation is guarded by EXISTS checks.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = [c["name"] for c in inspector.get_columns(table)]
    return column in cols


def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table in inspector.get_table_names()


def _index_exists(index: str, table: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(ix["name"] == index for ix in inspector.get_indexes(table))


def upgrade() -> None:
    # 1. CREATE TABLE IF NOT EXISTS projects
    if not _table_exists("projects"):
        op.create_table(
            "projects",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=False),
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    # 2. ADD COLUMN IF NOT EXISTS tasks.project_id
    if not _column_exists("tasks", "project_id"):
        op.add_column(
            "tasks",
            sa.Column(
                "project_id",
                postgresql.UUID(as_uuid=False),
                sa.ForeignKey("projects.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
    if not _index_exists("ix_tasks_project_id", "tasks"):
        op.create_index("ix_tasks_project_id", "tasks", ["project_id"])

    # 3. ADD COLUMN IF NOT EXISTS tasks.estimation_status
    if not _column_exists("tasks", "estimation_status"):
        op.add_column(
            "tasks",
            sa.Column(
                "estimation_status",
                sa.String(20),
                nullable=False,
                server_default="not_applicable",
            ),
        )

    # 4. ADD COLUMN IF NOT EXISTS tasks.cost
    if not _column_exists("tasks", "cost"):
        op.add_column(
            "tasks",
            sa.Column("cost", sa.Numeric(12, 2), nullable=True),
        )

    # 5. ADD COLUMN IF NOT EXISTS task_results.slot
    if not _column_exists("task_results", "slot"):
        op.add_column(
            "task_results",
            sa.Column(
                "slot",
                sa.String(20),
                nullable=False,
                server_default="result",
            ),
        )

    # 6. Backfill NULLs (safety net — server_default covers new rows,
    #    but existing rows added before column existed may be NULL)
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE tasks SET estimation_status = 'not_applicable' "
            "WHERE estimation_status IS NULL"
        )
    )
    bind.execute(
        sa.text(
            "UPDATE task_results SET slot = 'result' WHERE slot IS NULL"
        )
    )


def downgrade() -> None:
    # downgrade is intentionally a no-op: this migration only repairs
    # missing state; reversing it would destroy legitimate data.
    pass
