"""Имена владельцев для списков.

Проекты и задачи общие, поэтому в каждом списке важно видеть, чьё это —
владелец остаётся подписью «кто ведёт». Один хелпер на все роутеры, чтобы
имя собиралось везде одинаково (full_name → username → «#id»).
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


async def owner_names(owner_ids: list[int], db: AsyncSession) -> dict[int, str]:
    """{user_id: отображаемое имя (full_name или username)} для набора владельцев."""
    ids = [i for i in set(owner_ids) if i is not None]
    if not ids:
        return {}
    rows = (
        await db.execute(select(User.id, User.full_name, User.username).where(User.id.in_(ids)))
    ).all()
    return {r.id: (r.full_name or r.username or f"#{r.id}") for r in rows}
