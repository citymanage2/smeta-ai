"""Add price_lists table for uploaded price list file storage

Revision ID: 002
Revises: 001
Create Date: 2026-03-18 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table: str) -> bool:
    return table in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if not _table_exists("price_lists"):
        op.create_table(
            "price_lists",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("type", sa.String(20), nullable=False),
            sa.Column("filename", sa.String(255), nullable=False),
            sa.Column("mime_type", sa.String(100), nullable=False),
            sa.Column("content", sa.LargeBinary(), nullable=False),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.PrimaryKeyConstraint("id"),
        )
    op.execute("CREATE INDEX IF NOT EXISTS ix_price_lists_type ON price_lists (type)")


def downgrade() -> None:
    op.drop_index("ix_price_lists_type", table_name="price_lists")
    op.drop_table("price_lists")
