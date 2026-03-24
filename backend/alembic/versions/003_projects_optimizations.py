"""Projects, estimate items, task versions, new task fields

Revision ID: 003
Revises: 002
Create Date: 2026-03-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── projects ──────────────────────────────────────────────────────────
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
        sa.Column("user_id", sa.Integer(), nullable=True),
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_projects_user_id", "projects", ["user_id"])

    # ── new columns on tasks ──────────────────────────────────────────────
    op.add_column(
        "tasks",
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=False),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_tasks_project_id",
        "tasks",
        "projects",
        ["project_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_tasks_project_id", "tasks", ["project_id"])

    op.add_column(
        "tasks",
        sa.Column(
            "estimate_status",
            sa.String(50),
            nullable=False,
            server_default="uploaded",
        ),
    )
    op.add_column(
        "tasks",
        sa.Column("estimate_status_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tasks",
        sa.Column(
            "estimate_status_updated_by",
            sa.String(20),
            nullable=False,
            server_default="manual",
        ),
    )

    # ── task_versions ─────────────────────────────────────────────────────
    op.create_table(
        "task_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=False),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("task_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("change_description", sa.Text(), nullable=True),
        sa.Column("change_type", sa.String(50), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", sa.String(20), nullable=False, server_default="user"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_task_versions_task_id", "task_versions", ["task_id"])

    # ── estimate_items ────────────────────────────────────────────────────
    op.create_table(
        "estimate_items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=False),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("task_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("unit", sa.String(100), nullable=True),
        sa.Column("quantity", sa.Float(), nullable=True),
        sa.Column("work_price", sa.Float(), nullable=True),
        sa.Column("mat_price", sa.Float(), nullable=True),
        sa.Column("section", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_analogue", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("original_item_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("analogue_note", sa.Text(), nullable=True),
        sa.Column("extra", postgresql.JSONB(), nullable=False, server_default="{}"),
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
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["original_item_id"], ["estimate_items.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_estimate_items_task_id", "estimate_items", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_estimate_items_task_id", table_name="estimate_items")
    op.drop_table("estimate_items")

    op.drop_index("ix_task_versions_task_id", table_name="task_versions")
    op.drop_table("task_versions")

    op.drop_column("tasks", "estimate_status_updated_by")
    op.drop_column("tasks", "estimate_status_updated_at")
    op.drop_column("tasks", "estimate_status")
    op.drop_constraint("fk_tasks_project_id", "tasks", type_="foreignkey")
    op.drop_index("ix_tasks_project_id", table_name="tasks")
    op.drop_column("tasks", "project_id")

    op.drop_index("ix_projects_user_id", table_name="projects")
    op.drop_table("projects")
