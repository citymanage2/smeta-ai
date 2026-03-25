"""Add projects table, task project/estimation fields, task_results slot

Revision ID: 004
Revises: 003
Create Date: 2026-03-26 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "004"
down_revision: Union[str, None] = "003"
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


def upgrade() -> None:
    # 1. Create projects table
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

    # 2. Add project_id to tasks
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
        op.create_index("ix_tasks_project_id", "tasks", ["project_id"])

    # 3. Add estimation_status to tasks
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

    # 4. Add cost to tasks
    if not _column_exists("tasks", "cost"):
        op.add_column(
            "tasks",
            sa.Column("cost", sa.Numeric(12, 2), nullable=True),
        )

    # 5. Add slot to task_results
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


def downgrade() -> None:
    op.drop_column("task_results", "slot")
    op.drop_column("tasks", "cost")
    op.drop_column("tasks", "estimation_status")
    op.drop_index("ix_tasks_project_id", table_name="tasks")
    op.drop_column("tasks", "project_id")
    op.drop_table("projects")
