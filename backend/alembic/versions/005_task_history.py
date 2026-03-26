"""Add task_history table

Revision ID: 005
Revises: 004
Create Date: 2026-03-26 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table in inspector.get_table_names()


def upgrade() -> None:
    if not _table_exists("task_history"):
        op.create_table(
            "task_history",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=False),
                nullable=False,
            ),
            sa.Column(
                "task_id",
                postgresql.UUID(as_uuid=False),
                nullable=False,
            ),
            sa.Column("operation_type", sa.String(20), nullable=False),
            sa.Column("slot", sa.String(20), nullable=False),
            sa.Column(
                "description",
                sa.String(500),
                nullable=False,
                server_default="",
            ),
            sa.Column(
                "previous_value",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column(
                "new_value",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.ForeignKeyConstraint(
                ["task_id"],
                ["tasks.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_task_history_task_id_created_at",
            "task_history",
            ["task_id", "created_at"],
        )


def downgrade() -> None:
    op.drop_index("ix_task_history_task_id_created_at", table_name="task_history")
    op.drop_table("task_history")
