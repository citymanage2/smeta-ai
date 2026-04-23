"""Добавить таблицу estimate_versions

Revision ID: 014
Revises: 013
Create Date: 2026-04-23 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table in inspector.get_table_names()


def upgrade() -> None:
    if not _table_exists("estimate_versions"):
        op.create_table(
            "estimate_versions",
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
            sa.Column("version_number", sa.Integer(), nullable=False),
            sa.Column("version_label", sa.String(50), nullable=False),
            sa.Column("version_display_name", sa.String(200), nullable=False),
            sa.Column(
                "rows",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            ),
            sa.Column(
                "overhead_pct",
                sa.Numeric(5, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "transport_pct",
                sa.Numeric(5, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "contingency_pct",
                sa.Numeric(5, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "expenses_overridden",
                sa.Boolean(),
                nullable=False,
                server_default="false",
            ),
            sa.Column(
                "optimization_proposals",
                sa.JSON(),
                nullable=True,
            ),
            sa.Column(
                "is_rolled_back",
                sa.Boolean(),
                nullable=False,
                server_default="false",
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
            "ix_estimate_versions_task_id",
            "estimate_versions",
            ["task_id"],
        )


def downgrade() -> None:
    op.drop_index("ix_estimate_versions_task_id", table_name="estimate_versions")
    op.drop_table("estimate_versions")
