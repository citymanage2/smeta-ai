"""Имя файла сметы и оптимизации — по названию карточки.

У задач «Смета» и «Оптимизация» своего названия нет: их создаёт этап карточки,
а не человек. Раньше файл получал запасное имя «Смета_из_перечня.xlsx» /
«optimized.xlsx», и сметы одного проекта в папке загрузок было не различить.

Карточка же названа по исходному файлу: «Перечень из Гранд-сметы: ПОМЕЩЕНИЯ №93»
(`TaskCreate.buildAutoName`). Часть после двоеточия и есть то, что отличает
сметы проекта друг от друга, — её файл и повторяет: «Смета_ПОМЕЩЕНИЯ_№93.xlsx».
"""
from __future__ import annotations

import re
from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

_FORBIDDEN = re.compile(r'[\\/:*?"<>|]')
_MAX_LEN = 100


def safe_file_stem(text: str) -> str:
    """Текст → часть имени файла: без запрещённых символов, пробелы в «_»."""
    safe = _FORBIDDEN.sub("_", text.strip())
    safe = re.sub(r"\s+", "_", safe)
    return safe[:_MAX_LEN].strip("_.")


def card_label(card_name: Optional[str]) -> Optional[str]:
    """Отличительная часть названия карточки — всё после первого двоеточия.

    Двоеточия нет (карточку назвали руками) — название целиком.
    """
    name = (card_name or "").strip()
    if ":" in name:
        tail = name.split(":", 1)[1].strip()
        name = tail or name
    return name or None


def stage_file_name(prefix: str, card_name: Optional[str]) -> Optional[str]:
    """«Смета» + «Перечень из Гранд-сметы: ПОМЕЩЕНИЯ №93» → «Смета_ПОМЕЩЕНИЯ_№93.xlsx»."""
    label = card_label(card_name)
    stem = safe_file_stem(label) if label else ""
    if not stem:
        return None
    return f"{prefix}_{stem}.xlsx"


async def card_name_for_task(db: AsyncSession, task_id: str) -> Optional[str]:
    """Название карточки, к любому этапу которой привязана задача."""
    from app.models.workflow_card import WorkflowCard

    tid = str(task_id)
    res = await db.execute(
        select(WorkflowCard.name).where(or_(
            WorkflowCard.estimate_task_id == tid,
            WorkflowCard.optimization_task_id == tid,
            WorkflowCard.list_task_id == tid,
            WorkflowCard.completeness_task_id == tid,
        )).limit(1)
    )
    return res.scalar_one_or_none()


async def task_file_name(
    db: AsyncSession, task_id: str, prefix: str, fallback: str,
) -> str:
    """Имя файла этапа по карточке задачи; карточки нет — прежнее запасное имя."""
    return stage_file_name(prefix, await card_name_for_task(db, task_id)) or fallback
