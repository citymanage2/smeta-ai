from typing import Optional
from sqlalchemy import Integer, String, DateTime, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime, timezone
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Индивидуальный логин человека. nullable для legacy-записей ролей user/admin
    # (общие пароли), которые username не имеют. unique — на непустых значениях.
    username: Mapped[Optional[str]] = mapped_column(String(50), unique=True, nullable=True, index=True)
    # Роли: 'admin', 'head_of_sales', 'project_manager'. Legacy 'user' трактуется
    # как project_manager (наименьшие права). Ширина 32 — под длинные имена ролей.
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    # ФИО для отображения владельца на карточках проектов/задач.
    full_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # Деактивация вместо удаления: сохраняет owner_id ссылок на проекты/задачи.
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
