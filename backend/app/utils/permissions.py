"""Матрица прав доступа (RBAC).

Единая точка правил для трёх ролей. Проекты и задачи — общие: любой сотрудник
видит и правит работу коллег (решение пользователя 11.08.2026). Роль решает
только «управляющие» действия: переназначение владельца, аккаунты, прайсы,
админка. Владелец (`owner_id`) остаётся у ресурса как подпись «чьё это» и
используется в очереди задач и при массовой очистке корзины, но доступ больше
не ограничивает.
Архив (`is_archived`) ортогонален правам — он влияет только на раздел
(активные/архив), а не на видимость/правку.

Зависимость односторонняя: permissions → auth (без циклов).
"""
from typing import Optional

from fastapi import Depends, HTTPException, status
from sqlalchemy.sql.elements import ColumnElement

from app.utils.auth import get_current_user

# --- Роли ---
ROLE_ADMIN = "admin"
ROLE_SALES_HEAD = "head_of_sales"
ROLE_PM = "project_manager"

# Менеджеры — управляющие действия (переназначение владельца, аккаунты, прайсы).
# Данные проектов и задач видят и правят все роли одинаково.
MANAGER_ROLES = frozenset({ROLE_ADMIN, ROLE_SALES_HEAD})
# Роли, допустимые при создании/смене аккаунта (legacy 'user' — не создаём).
ASSIGNABLE_ROLES = frozenset({ROLE_ADMIN, ROLE_SALES_HEAD, ROLE_PM})


def normalize_role(role: Optional[str]) -> str:
    """Каноническая роль. Legacy 'user' и неизвестное → project_manager (мин. права)."""
    return role if role in {ROLE_ADMIN, ROLE_SALES_HEAD, ROLE_PM} else ROLE_PM


def is_admin(role: Optional[str]) -> bool:
    return normalize_role(role) == ROLE_ADMIN


def is_manager(role: Optional[str]) -> bool:
    """Админ или руководитель отдела продаж — управляющие действия."""
    return normalize_role(role) in MANAGER_ROLES


def can_reassign(role: Optional[str]) -> bool:
    """Переназначать владельца проекта/задачи может только менеджер."""
    return is_manager(role)


def visibility_filter(model, current_user: dict) -> Optional[ColumnElement]:
    """SQLAlchemy-условие фильтра списков по владельцу.

    Всегда None — «без фильтра»: проекты и задачи общие, каждый сотрудник видит
    работу коллег. Функция сохранена как единственная точка правила: роутеры уже
    умеют None, и если видимость снова сузят — правка здесь, а не в двух десятках
    запросов. Архив здесь НЕ учитывается — по is_archived роутер фильтрует
    отдельно.
    """
    return None


def can_access(
    resource_owner_id: Optional[int], current_user: dict, is_shared: bool = False
) -> bool:
    """Может ли пользователь видеть/править конкретный проект или задачу.

    Всегда True: проекты и задачи общие для всех сотрудников независимо от роли
    и владельца. Единственная точка правила — сузить доступ можно здесь.
    Управляющие действия (переназначение владельца, аккаунты, прайсы) проверяются
    отдельно через is_manager/get_manager_user, а массовая очистка корзины — по
    owner_id прямо в роутере задач.
    """
    return True


# Правка = доступ. Отдельная функция для читаемости вызовов в роутерах.
can_edit = can_access


async def get_manager_user(current_user: dict = Depends(get_current_user)) -> dict:
    """Зависимость: требует роль менеджера (admin | head_of_sales)."""
    if not is_manager(current_user.get("role")):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Недостаточно прав. Требуется роль руководителя или администратора",
        )
    return current_user
