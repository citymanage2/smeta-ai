"""Разделы сводной в едином редакторе: черновик, rev, коэффициент

Revision ID: 043
Revises: 042
Create Date: 2026-08-02 00:00:00.000000

План: plans/2026-08-02-edinyy-redaktor-tablic.md, Фаза 7.

Раздел сводной получает то же поведение, что остальные документы: черновик до
«Применить», защиту от перезаписи чужих правок и коэффициент. Строки раздела
здесь НЕ дублируются — они остаются в `summary_estimates.sections`, чтобы у
строки, как и у сметы после Фазы 5, было ровно одно хранилище.

Все операции идемпотентны (IF NOT EXISTS): миграцию безопасно перезапускать.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "043"
down_revision: Union[str, None] = "042"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS summary_section_docs (
            id UUID PRIMARY KEY,
            summary_id UUID NOT NULL REFERENCES summary_estimates(id) ON DELETE CASCADE,
            card_id UUID NOT NULL REFERENCES workflow_cards(id) ON DELETE CASCADE,
            draft_rows JSON,
            draft_updated_at TIMESTAMPTZ,
            draft_user_id INTEGER,
            rev INTEGER NOT NULL DEFAULT 0,
            coefficient JSON,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_summary_section_docs_summary_id "
        "ON summary_section_docs (summary_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_summary_section_docs_card_id "
        "ON summary_section_docs (card_id)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_summary_section_docs_pair "
        "ON summary_section_docs (summary_id, card_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS summary_section_docs")
