"""Матрица прав доступа (RBAC).

Единая точка правил для трёх ролей. Доступ определяется владельцем ресурса
(`owner_id`) и ролью пользователя. Архив (`is_archived`) ортогонален правам —
он влияет только на раздел (активные/архив), а не на видимость/правку.

Зависимость односторонняя: permissions → auth (без циклов).
"""
from typing import Optional

from fastapi import Depends, HTTPException, status
from sqlalchemy import false
from sqlalchemy.sql.elements import ColumnElement

from app.utils.auth import get_current_user, current_user_id

# --- Роли ---
ROLE_ADMIN = "admin"
ROLE_SALES_HEAD = "head_of_sales"
ROLE_PM = "project_manager"

# Менеджеры видят и правят всё, могут переназначать владельца.
MANAGER_ROLES = frozenset({ROLE_ADMIN, ROLE_SALES_HEAD})
# Роли, допустимые при создании/смене аккаунта (legacy 'user' — не создаём).
ASSIGNABLE_ROLES = frozenset({ROLE_ADMIN, ROLE_SALES_HEAD, ROLE_PM})


def normalize_role(role: Optional[str]) -> str:
    """Каноническая роль. Legacy 'user' и неизвестное → project_manager (мин. права)."""
    return role if role in {ROLE_ADMIN, ROLE_SALES_HEAD, ROLE_PM} else ROLE_PM


def is_admin(role: Optional[str]) -> bool:
    return normalize_role(role) == ROLE_ADMIN


def is_manager(role: Optional[str]) -> bool:
    """Админ или руководитель отдела продаж — полный доступ к данным."""
    return normalize_role(role) in MANAGER_ROLES


def can_reassign(role: Optional[str]) -> bool:
    """Переназначать владельца проекта/задачи может только менеджер."""
    return is_manager(role)


def visibility_filter(model, current_user: dict) -> Optional[ColumnElement]:
    """SQLAlchemy-условие фильтра по владельцу для списков.

    None → без фильтра (менеджер видит всё). Для ПМ — только свои строки.
    ПМ без owner_id (legacy shared-токен) не видит ничего персонального.
    Архив здесь НЕ учитывается — фильтр по is_archived роутер добавляет отдельно.
    """
    if is_manager(current_user.get("role")):
        return None
    uid = current_user_id(current_user)
    if uid is None:
        return false()
    return model.owner_id == uid


def can_access(resource_owner_id: Optional[int], current_user: dict) -> bool:
    """Может ли пользователь видеть/править конкретный ресурс (по его owner_id).

    Видимость и правка совпадают: ПМ работает только со своими ресурсами,
    менеджер — с любыми.
    """
    if is_manager(current_user.get("role")):
        return True
    uid = current_user_id(current_user)
    return uid is not None and resource_owner_id is not None and resource_owner_id == uid


# Правка = доступ (ПМ правит только своё, менеджер — любое). Отдельная функция
# для читаемости вызовов в роутерах.
can_edit = can_access


async def get_manager_user(current_user: dict = Depends(get_current_user)) -> dict:
    """Зависимость: требует роль менеджера (admin | head_of_sales)."""
    if not is_manager(current_user.get("role")):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Недостаточно прав. Требуется роль руководителя или администратора",
        )
    return current_user
