"""Initial migration - create all tables

Revision ID: 001
Revises: 
Create Date: 2025-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    # Create users table (IF NOT EXISTS)
    if "users" not in existing:
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("role", sa.String(10), nullable=False),
            sa.Column("password_hash", sa.String(255), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    # Create tasks table (IF NOT EXISTS)
    if "tasks" not in existing:
        op.create_table(
            "tasks",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=False),
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("user_role", sa.String(10), nullable=False),
            sa.Column("task_type", sa.String(50), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("input_files", postgresql.JSONB(), nullable=False, server_default="[]"),
            sa.Column("input_file_data", postgresql.JSONB(), nullable=False, server_default="[]"),
            sa.Column("user_prompt", sa.Text(), nullable=True),
            sa.Column("chat_history", postgresql.JSONB(), nullable=False, server_default="[]"),
            sa.Column("progress_message", sa.String(500), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
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
        op.create_index("ix_tasks_status", "tasks", ["status"])
        op.create_index("ix_tasks_created_at", "tasks", ["created_at"])

    # Create task_results table (IF NOT EXISTS)
    if "task_results" not in existing:
        op.create_table(
            "task_results",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column(
                "task_id",
                postgresql.UUID(as_uuid=False),
                nullable=False,
            ),
            sa.Column("file_name", sa.String(255), nullable=False),
            sa.Column("mime_type", sa.String(100), nullable=False),
            sa.Column("file_data", sa.LargeBinary(), nullable=False),
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
        op.create_index("ix_task_results_task_id", "task_results", ["task_id"])

    # Create price_works table (IF NOT EXISTS)
    if "price_works" not in existing:
        op.create_table(
            "price_works",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("unit", sa.String(50), nullable=True),
            sa.Column("prices", postgresql.JSONB(), nullable=False, server_default="{}"),
            sa.Column("min_price", sa.Float(), nullable=True),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    # Create price_materials table (IF NOT EXISTS)
    if "price_materials" not in existing:
        op.create_table(
            "price_materials",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("unit", sa.String(50), nullable=True),
            sa.Column("price", sa.Float(), nullable=True),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.PrimaryKeyConstraint("id"),
        )


def downgrade() -> None:
    op.drop_table("price_materials")
    op.drop_table("price_works")
    op.drop_index("ix_task_results_task_id", table_name="task_results")
    op.drop_table("task_results")
    op.drop_index("ix_tasks_created_at", table_name="tasks")
    op.drop_index("ix_tasks_status", table_name="tasks")
    op.drop_table("tasks")
    op.drop_table("users")
