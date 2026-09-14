"""Правила из правок, которые человек включил, — отдельным блоком промпта.

План: plans/2026-09-10-sverka-i-obuchenie-na-pravkah.md, Фаза 8.

Правила — не бесплатное улучшение: шумные указания в промпте ухудшают ответ
модели, а не улучшают. Поэтому:

- в промпт идут только включённые человеком правила (правило 9 CLAUDE.md);
- число и суммарная длина ограничены — включить сверх лимита нельзя;
- правил нет — промпт байт в байт прежний (`system_for` возвращает строку);
- набор читается **один раз на задачу**: правило, включённое посреди расчёта,
  иначе отправило бы один расчёт по двум разным промптам.

Правила действуют только на стадии, которые используют `SYSTEM_BASE`: перечень,
полнота, смета и нормы. Оптимизация, добор цен, цена одной позиции и поиск
аналогов их не получают — это видно в интерфейсе.
"""
from __future__ import annotations

from typing import Optional, Union

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.prompt_rule import SCOPE_ALL, PromptRule

MAX_ACTIVE_RULES = 20
MAX_TOTAL_CHARS = 4000
MAX_RULE_CHARS = 500

BLOCK_HEADER = (
    "Правила, подтверждённые сметчиками компании по итогам ручных правок. "
    "Соблюдай их, если они относятся к позиции:"
)


def applies(rule: PromptRule, task_type: Optional[str]) -> bool:
    return rule.scope == SCOPE_ALL or (task_type or "").upper() == rule.scope


def build_block(rules: list[PromptRule], task_type: Optional[str]) -> Optional[str]:
    """Текст блока правил для задачи или None, если применимых правил нет."""
    lines = [
        f"- {rule.text.strip()}"
        for rule in rules
        if rule.enabled and rule.text and rule.text.strip() and applies(rule, task_type)
    ]
    if not lines:
        return None
    return BLOCK_HEADER + "\n" + "\n".join(lines)


async def load_block(db: AsyncSession, task_type: Optional[str]) -> Optional[str]:
    rules = (await db.execute(
        select(PromptRule).where(PromptRule.enabled.is_(True)).order_by(PromptRule.id)
    )).scalars().all()
    return build_block(list(rules), task_type)


def system_for(base: str, block: Optional[str]) -> Union[str, list[str]]:
    """Основной промпт плюс блок правил. Нет правил — ровно прежняя строка."""
    return [base, block] if block else base


async def check_can_enable(db: AsyncSession, rule: PromptRule) -> Optional[str]:
    """Причина отказа включить правило или None, если можно."""
    active = (await db.execute(
        select(PromptRule).where(PromptRule.enabled.is_(True), PromptRule.id != rule.id)
    )).scalars().all()
    if len(active) >= MAX_ACTIVE_RULES:
        return (
            f"Включено уже {len(active)} правил — это предел. Много указаний "
            "в промпте ухудшают ответ модели; выключите устаревшее правило."
        )
    total = sum(len(r.text or "") for r in active) + len(rule.text or "")
    if total > MAX_TOTAL_CHARS:
        return (
            f"Суммарная длина правил превысит {MAX_TOTAL_CHARS} знаков. "
            "Сократите формулировки или выключите устаревшее правило."
        )
    return None
