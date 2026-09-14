"""КП: подсказки ИИ-разбора (НДС, ставка, «включает материалы»)

Revision ID: 053
Revises: 052
Create Date: 2026-09-15 00:00:00.000000

План: plans/2026-09-14-zapros-kp.md, Фаза 6. Догадка ИИ заполняет только пустые
поля КП, а режим НДС и ставку человек выбирает при загрузке сам — пустыми они
не бывают. Поэтому догадки о НДС и отметка «включает материалы» (её ставит
человек) хранятся рядом, подсказкой, и показываются в заголовке колонки КП.

Идемпотентно (IF NOT EXISTS).
"""
from typing import Sequence, Union

from alembic import op

revision: str = "053"
down_revision: Union[str, None] = "052"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE kp_offers ADD COLUMN IF NOT EXISTS parse_hints JSONB")


def downgrade() -> None:
    op.execute("ALTER TABLE kp_offers DROP COLUMN IF EXISTS parse_hints")
