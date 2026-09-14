"""Запрос КП у отдела производства работ: запросы, вложения, позиции, КП, цены

Revision ID: 052
Revises: 051
Create Date: 2026-09-14 00:00:00.000000

План: plans/2026-09-14-zapros-kp.md, Фаза 2 (раздел «Модель данных»).

Порядок таблиц — по внешним ключам: позиция ссылается на выбранное КП, поэтому
`kp_offers` создаётся раньше `kp_request_items`.

Все операции идемпотентны (IF NOT EXISTS): миграцию безопасно перезапускать.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "052"
down_revision: Union[str, None] = "051"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS kp_requests (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            card_id UUID NOT NULL REFERENCES workflow_cards(id) ON DELETE CASCADE,
            source_kind VARCHAR(16) NOT NULL,
            source_task_id UUID,
            source_version_id UUID,
            category VARCHAR(16) NOT NULL,
            target_role VARCHAR(32) NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'new',
            author_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            taken_by_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            taken_at TIMESTAMPTZ,
            completed_by_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            completed_at TIMESTAMPTZ,
            author_comment TEXT,
            report TEXT,
            pricelist_status VARCHAR(16),
            pricelist_summary JSONB,
            pricelist_error TEXT,
            pricelist_written_at TIMESTAMPTZ,
            applied_at TIMESTAMPTZ,
            applied_version_id UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_kp_requests_role_status "
        "ON kp_requests (target_role, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_kp_requests_card_id ON kp_requests (card_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS kp_request_files (
            id UUID PRIMARY KEY,
            request_id UUID NOT NULL REFERENCES kp_requests(id) ON DELETE CASCADE,
            file_name VARCHAR(255) NOT NULL,
            mime_type VARCHAR(255) NOT NULL,
            size_bytes INTEGER NOT NULL,
            storage_key VARCHAR(512) NOT NULL,
            uploaded_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_kp_request_files_request_id "
        "ON kp_request_files (request_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS kp_offers (
            id UUID PRIMARY KEY,
            request_id UUID NOT NULL REFERENCES kp_requests(id) ON DELETE CASCADE,
            supplier_name TEXT NOT NULL DEFAULT '',
            offer_date DATE,
            vat_mode VARCHAR(16) NOT NULL DEFAULT 'without_vat',
            vat_rate NUMERIC(5, 2),
            includes_materials BOOLEAN NOT NULL DEFAULT false,
            file_name VARCHAR(255),
            mime_type VARCHAR(255),
            size_bytes INTEGER,
            storage_key VARCHAR(512),
            parse_status VARCHAR(16),
            parse_error TEXT,
            parse_started_at TIMESTAMPTZ,
            parse_cost NUMERIC,
            created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_kp_offers_request_id ON kp_offers (request_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS kp_request_items (
            id UUID PRIMARY KEY,
            request_id UUID NOT NULL REFERENCES kp_requests(id) ON DELETE CASCADE,
            position INTEGER NOT NULL DEFAULT 0,
            item_type VARCHAR(16) NOT NULL,
            name TEXT NOT NULL,
            unit VARCHAR(64),
            qty NUMERIC,
            sheet VARCHAR(128),
            source_no VARCHAR(64),
            source_row_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
            selected_offer_id UUID REFERENCES kp_offers(id) ON DELETE SET NULL
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_kp_request_items_request_id "
        "ON kp_request_items (request_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS kp_offer_prices (
            id UUID PRIMARY KEY,
            offer_id UUID NOT NULL REFERENCES kp_offers(id) ON DELETE CASCADE,
            item_id UUID NOT NULL REFERENCES kp_request_items(id) ON DELETE CASCADE,
            price NUMERIC NOT NULL,
            unit VARCHAR(64),
            name_in_offer TEXT,
            includes_materials BOOLEAN,
            source VARCHAR(8) NOT NULL DEFAULT 'manual',
            confidence VARCHAR(8),
            confirmed BOOLEAN NOT NULL DEFAULT false,
            CONSTRAINT uq_kp_offer_prices_offer_item UNIQUE (offer_id, item_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_kp_offer_prices_offer_id ON kp_offer_prices (offer_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_kp_offer_prices_item_id ON kp_offer_prices (item_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS kp_offer_prices")
    op.execute("DROP TABLE IF EXISTS kp_request_items")
    op.execute("DROP TABLE IF EXISTS kp_offers")
    op.execute("DROP TABLE IF EXISTS kp_request_files")
    op.execute("DROP TABLE IF EXISTS kp_requests")
