"""Фундамент единого редактора: черновики, rev, коэффициент, автор правки, присутствие

Revision ID: 042
Revises: 041
Create Date: 2026-08-02 00:00:00.000000

План: plans/2026-08-02-edinyy-redaktor-tablic.md, Фаза 1.

Что добавляется:
  * estimate_versions.draft_rows / draft_updated_at / draft_user_id — черновик,
    который живёт до нажатия «Применить» и не влияет ни на rows, ни на файл;
  * estimate_versions.rev — счётчик применённых изменений; клиент присылает свой
    rev, расхождение = кто-то сохранил раньше → 409 вместо тихого затирания;
  * estimate_versions.coefficient — обратимый коэффициент к ценам (Фаза 8),
    колонка заводится сейчас, чтобы не плодить вторую миграцию;
  * task_history.user_id / user_name / document_kind — «кто и что именно правил»;
  * projects.overhead_pct / transport_pct — проценты доп. расходов на уровне
    проекта, по умолчанию прежние 3% (поведение не меняется);
  * document_locks — присутствие «Иван сейчас редактирует».

Все операции идемпотентны (IF NOT EXISTS): миграцию безопасно перезапускать.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "042"
down_revision: Union[str, None] = "041"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Черновик, счётчик изменений, коэффициент ---
    op.execute("ALTER TABLE estimate_versions ADD COLUMN IF NOT EXISTS draft_rows JSON")
    op.execute(
        "ALTER TABLE estimate_versions ADD COLUMN IF NOT EXISTS draft_updated_at TIMESTAMPTZ"
    )
    op.execute(
        "ALTER TABLE estimate_versions ADD COLUMN IF NOT EXISTS draft_user_id INTEGER"
    )
    op.execute(
        "ALTER TABLE estimate_versions ADD COLUMN IF NOT EXISTS rev INTEGER NOT NULL DEFAULT 0"
    )
    op.execute("ALTER TABLE estimate_versions ADD COLUMN IF NOT EXISTS coefficient JSON")

    # --- Автор правки в истории ---
    op.execute("ALTER TABLE task_history ADD COLUMN IF NOT EXISTS user_id INTEGER")
    op.execute("ALTER TABLE task_history ADD COLUMN IF NOT EXISTS user_name VARCHAR(120)")
    op.execute(
        "ALTER TABLE task_history ADD COLUMN IF NOT EXISTS document_kind VARCHAR(30)"
    )

    # --- Проценты доп. расходов на уровне проекта ---
    op.execute(
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS "
        "overhead_pct NUMERIC(5,2) NOT NULL DEFAULT 3"
    )
    op.execute(
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS "
        "transport_pct NUMERIC(5,2) NOT NULL DEFAULT 3"
    )

    # --- Присутствие в документе ---
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS document_locks (
            id UUID PRIMARY KEY,
            card_id UUID NOT NULL REFERENCES workflow_cards(id) ON DELETE CASCADE,
            kind VARCHAR(30) NOT NULL,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            user_name VARCHAR(120) NOT NULL DEFAULT '',
            heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_document_locks_card_id ON document_locks (card_id)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_document_locks_card_kind "
        "ON document_locks (card_id, kind)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS document_locks")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS transport_pct")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS overhead_pct")
    op.execute("ALTER TABLE task_history DROP COLUMN IF EXISTS document_kind")
    op.execute("ALTER TABLE task_history DROP COLUMN IF EXISTS user_name")
    op.execute("ALTER TABLE task_history DROP COLUMN IF EXISTS user_id")
    op.execute("ALTER TABLE estimate_versions DROP COLUMN IF EXISTS coefficient")
    op.execute("ALTER TABLE estimate_versions DROP COLUMN IF EXISTS rev")
    op.execute("ALTER TABLE estimate_versions DROP COLUMN IF EXISTS draft_user_id")
    op.execute("ALTER TABLE estimate_versions DROP COLUMN IF EXISTS draft_updated_at")
    op.execute("ALTER TABLE estimate_versions DROP COLUMN IF EXISTS draft_rows")
