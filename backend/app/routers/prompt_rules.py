"""Правила для промпта: создать, поправить, включить, выключить, удалить.

План: plans/2026-09-10-sverka-i-obuchenie-na-pravkah.md, Фаза 8.

Доступ — менеджерам: правило меняет все будущие расчёты и невидимо в
результате. Проверка роли — через `get_manager_user`, как у прайса.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import TASK_TYPE_LABELS
from app.database import get_db
from app.models.prompt_rule import SCOPE_ALL, PromptRule
from app.services import prompt_rules as svc
from app.utils.permissions import get_manager_user

router = APIRouter(prefix="/prompt-rules", tags=["prompt-rules"])


class RuleIn(BaseModel):
    text: str = Field(min_length=1, max_length=svc.MAX_RULE_CHARS)
    scope: str = SCOPE_ALL


class RuleOut(BaseModel):
    id: int
    text: str
    scope: str
    enabled: bool
    created_by: Optional[str] = None
    enabled_by: Optional[str] = None
    enabled_at: Optional[str] = None
    created_at: str


def _out(rule: PromptRule) -> RuleOut:
    return RuleOut(
        id=rule.id, text=rule.text, scope=rule.scope, enabled=rule.enabled,
        created_by=rule.created_by, enabled_by=rule.enabled_by,
        enabled_at=rule.enabled_at.isoformat() if rule.enabled_at else None,
        created_at=rule.created_at.isoformat() if rule.created_at else "",
    )


async def _who(db: AsyncSession, user: dict) -> str:
    """ФИО из базы: в токене его нет, а подпись «кто включил» обязана быть читаемой."""
    from app.services.document_service import user_display_name

    return await user_display_name(db, user)


def _check_scope(scope: str) -> str:
    scope = (scope or SCOPE_ALL).upper()
    if scope != SCOPE_ALL and scope not in TASK_TYPE_LABELS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Неизвестная область правила")
    return scope


async def _get(db: AsyncSession, rule_id: int) -> PromptRule:
    rule = await db.get(PromptRule, rule_id)
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Правило не найдено")
    return rule


@router.get("", response_model=list[RuleOut])
async def list_rules(db: AsyncSession = Depends(get_db), user: dict = Depends(get_manager_user)):
    rows = (await db.execute(select(PromptRule).order_by(PromptRule.id))).scalars().all()
    return [_out(r) for r in rows]


@router.post("", response_model=RuleOut)
async def create_rule(body: RuleIn, db: AsyncSession = Depends(get_db),
                      user: dict = Depends(get_manager_user)):
    """Новое правило создаётся выключенным: включение — отдельное решение."""
    rule = PromptRule(text=body.text.strip(), scope=_check_scope(body.scope),
                      enabled=False, created_by=await _who(db, user))
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return _out(rule)


@router.put("/{rule_id}", response_model=RuleOut)
async def update_rule(rule_id: int, body: RuleIn, db: AsyncSession = Depends(get_db),
                      user: dict = Depends(get_manager_user)):
    rule = await _get(db, rule_id)
    rule.text = body.text.strip()
    rule.scope = _check_scope(body.scope)
    if rule.enabled:
        reason = await svc.check_can_enable(db, rule)
        if reason:
            raise HTTPException(status.HTTP_409_CONFLICT, detail=reason)
    rule.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return _out(rule)


@router.post("/{rule_id}/enable", response_model=RuleOut)
async def enable_rule(rule_id: int, db: AsyncSession = Depends(get_db),
                      user: dict = Depends(get_manager_user)):
    rule = await _get(db, rule_id)
    reason = await svc.check_can_enable(db, rule)
    if reason:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=reason)
    now = datetime.now(timezone.utc)
    rule.enabled, rule.enabled_by, rule.enabled_at, rule.updated_at = True, await _who(db, user), now, now
    await db.commit()
    return _out(rule)


@router.post("/{rule_id}/disable", response_model=RuleOut)
async def disable_rule(rule_id: int, db: AsyncSession = Depends(get_db),
                       user: dict = Depends(get_manager_user)):
    rule = await _get(db, rule_id)
    rule.enabled = False
    rule.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return _out(rule)


@router.delete("/{rule_id}")
async def delete_rule(rule_id: int, db: AsyncSession = Depends(get_db),
                      user: dict = Depends(get_manager_user)):
    rule = await _get(db, rule_id)
    await db.delete(rule)
    await db.commit()
    return {"deleted": True}
