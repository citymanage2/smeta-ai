"""Операции над версиями сметы, общие для роутеров и сервисов.

`clone_version` — снимок версии новой версией. Вызывается ручной «Зафиксировать
версию» (`routers/estimate_versions.create_manual_version`) и применением цен
из КП к оптимизации (фаза 8 плана `plans/2026-09-14-zapros-kp.md`). Коммита
внутри нет: применение КП создаёт клон в одной транзакции со сверкой ревизии
и записью цен, и частично записанная версия не должна пережить сбой.
"""
from __future__ import annotations

import copy
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.estimate_version import EstimateVersion


# Слот файла заказчика: версия-клон туда не пишется никогда (правило №2 CLAUDE.md).
_INPUT_SLOT = "input"


async def next_version_number(db: AsyncSession, task_id: str) -> int:
    """Следующий номер версии задачи — сквозной по всем слотам и откатам."""
    current = (await db.execute(
        select(func.max(EstimateVersion.version_number))
        .where(EstimateVersion.task_id == task_id)
    )).scalar()
    return 0 if current is None else current + 1


async def clone_version(
    db: AsyncSession, source: EstimateVersion, name: str,
) -> EstimateVersion:
    """Новая версия с содержимым `source`: строки, проценты, коэффициент, тип.

    Не копируется состояние исходной версии — черновик, ревизия, откат и
    предложения оптимизации. Строки копируются глубоко: правка клона не
    меняет исходную версию. Делает `flush`, но не `commit`.
    """
    slot = source.file_slot or "result"
    clone = EstimateVersion(
        id=str(uuid.uuid4()),
        task_id=source.task_id,
        version_number=await next_version_number(db, source.task_id),
        version_label="custom",
        version_display_name=name,
        rows=copy.deepcopy(source.rows or []),
        overhead_pct=source.overhead_pct,
        transport_pct=source.transport_pct,
        contingency_pct=source.contingency_pct,
        expenses_overridden=source.expenses_overridden,
        coefficient=copy.deepcopy(source.coefficient),
        task_type=source.task_type,
        file_slot="result" if slot == _INPUT_SLOT else slot,
    )
    db.add(clone)
    await db.flush()
    return clone
