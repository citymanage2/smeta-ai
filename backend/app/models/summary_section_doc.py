import uuid as _uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SummarySectionDoc(Base):
    """Состояние раздела сводной в едином редакторе (план 2026-08-02, Фаза 7).

    Строк здесь нет намеренно. Строки раздела живут в
    `summary_estimates.sections[i]['rows']` и остаются единственным хранилищем —
    копия в отдельной таблице повторила бы ошибку сметы до Фазы 5, когда одна
    строка имела два значения в двух местах.

    Здесь лежит только то, чего у сводной не было: черновик до «Применить»,
    счётчик применённых изменений `rev` (защита от затирания чужих правок) и
    коэффициент (Фаза 8). Одна запись на пару (сводная, карточка-раздел).
    """

    __tablename__ = "summary_section_docs"
    __table_args__ = (
        UniqueConstraint("summary_id", "card_id", name="uq_summary_section_docs_pair"),
    )

    id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(_uuid.uuid4()),
    )
    summary_id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False),
        ForeignKey("summary_estimates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    card_id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False),
        ForeignKey("workflow_cards.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Черновик: правки автосохраняются сюда и не влияют на сводную, пока человек
    # не нажал «Применить».
    draft_rows: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    draft_updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    draft_user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Счётчик применённых изменений: клиент присылает свой rev, расхождение = 409.
    rev: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Обратимый коэффициент к ценам раздела (Фаза 8). Колонка заводится сейчас,
    # чтобы не плодить вторую миграцию.
    coefficient: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
