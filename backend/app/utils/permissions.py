"""Матрица прав доступа (RBAC).

Единая точка правил для ролей. Проекты и задачи — общие: любой сотрудник
видит и правит работу коллег (решение пользователя 11.08.2026). Роль решает
только «управляющие» действия: переназначение владельца, аккаунты, прайсы,
админка. Владелец (`owner_id`) остаётся у ресурса как подпись «чьё это» и
используется в очереди задач и при массовой очистке корзины, но доступ больше
не ограничивает.
Архив (`is_archived`) ортогонален правам — он влияет только на раздел
(активные/архив), а не на видимость/правку.

Отдел производства работ (снабжение и работа с подрядчиками, запрос КП от
14.09.2026) — исключение из «всё общее»: этим ролям по умолчанию закрыто всё API,
кроме входа и запросов КП. Запрет — зависимость `forbid_production_roles` на
каждом `include_router` в `main.py`, а не проверки в роутерах: половина ручек
`can_access` не зовёт, и новый роутер без явного разрешения обязан оказаться
закрытым (тест перебирает все маршруты, `tests/test_kp_roles_access.py`).

Зависимость односторонняя: permissions → auth (без циклов).
"""
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.database import get_db
from app.models.user import User
from app.utils.auth import (
    current_user_id,
    decode_token_or_none,
    get_current_user,
    raw_token_from_request,
)

# --- Роли ---
ROLE_ADMIN = "admin"
ROLE_SALES_HEAD = "head_of_sales"
ROLE_PM = "project_manager"
# Отдел производства работ: снабжение (материалы) и подрядчики (работы).
ROLE_SUPPLY = "supply_manager"
ROLE_CONTRACTOR = "contractor_manager"

# Менеджеры — управляющие действия (переназначение владельца, аккаунты, прайсы).
# Данные проектов и задач видят и правят все роли продаж одинаково.
MANAGER_ROLES = frozenset({ROLE_ADMIN, ROLE_SALES_HEAD})
# Роли отдела производства: закрыто всё, кроме запросов КП своей роли.
PRODUCTION_ROLES = frozenset({ROLE_SUPPLY, ROLE_CONTRACTOR})
# Роли, допустимые при создании/смене аккаунта (legacy 'user' — не создаём).
ASSIGNABLE_ROLES = frozenset({ROLE_ADMIN, ROLE_SALES_HEAD, ROLE_PM}) | PRODUCTION_ROLES
_KNOWN_ROLES = ASSIGNABLE_ROLES

# Кому адресован запрос КП по категории позиций.
KP_CATEGORY_ROLE = {"material": ROLE_SUPPLY, "work": ROLE_CONTRACTOR}

# Белый список производства: префиксы путей роутеров, на которые НЕ вешается
# `forbid_production_roles`. Вход — чтобы войти; остальное — запросы КП.
PRODUCTION_ALLOWED_PREFIXES = (
    "/auth",
    "/kp-requests",
    "/kp-request-files",
    "/kp-request-items",
    "/kp-offers",
)

PRODUCTION_FORBIDDEN_DETAIL = "Раздел недоступен отделу производства работ"


def normalize_role(role: Optional[str]) -> str:
    """Каноническая роль. Legacy 'user' и неизвестное → project_manager.

    Роли производства перечислены явно: иначе они молча стали бы ПМ — а ПМ
    видит и правит все проекты.
    """
    return role if role in _KNOWN_ROLES else ROLE_PM


def is_production(role: Optional[str]) -> bool:
    """Роль отдела производства работ (снабжение или подрядчики)."""
    return role in PRODUCTION_ROLES


def is_production_allowed_path(path: str) -> bool:
    """Путь из белого списка производства (совпадение по сегменту, не по началу строки)."""
    return any(path == p or path.startswith(p + "/") for p in PRODUCTION_ALLOWED_PREFIXES)


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


# --- Запрос КП ---------------------------------------------------------------
# Объект запроса — любой с полями `target_role` и `author_id` (модель KpRequest).
# Роль пользователя — действующая: роутер КП подставляет роль из БД (см.
# `routers/kp_requests.get_kp_user`), чтобы смена роли не ждала перелогина.

def can_view_kp(request, current_user: dict) -> bool:
    """Видит ли пользователь запрос КП.

    Продажи видят все запросы — проекты общие. Производство — только запросы,
    адресованные своей роли; чужой запрос для него не существует (роутер
    отвечает 404, как на несуществующий).
    """
    role = current_user.get("role")
    if is_production(role):
        return request.target_role == role
    return True


def can_work_kp(request, current_user: dict) -> bool:
    """Может ли пользователь исполнять запрос: брать в работу, грузить КП,
    вводить цены, завершать. Только сотрудник роли, которой запрос адресован —
    любой из них, а не только взявший: запрос адресован роли целиком."""
    role = current_user.get("role")
    return is_production(role) and request.target_role == role


def can_manage_kp(request, current_user: dict) -> bool:
    """Отменить запрос или вернуть его в работу: автор или руководитель продаж
    (админ — тоже). Производство — никогда, даже если числится автором."""
    role = current_user.get("role")
    if is_production(role):
        return False
    if is_manager(role):
        return True
    uid = current_user_id(current_user)
    return uid is not None and request.author_id == uid


async def get_manager_user(current_user: dict = Depends(get_current_user)) -> dict:
    """Зависимость: требует роль менеджера (admin | head_of_sales)."""
    if not is_manager(current_user.get("role")):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Недостаточно прав. Требуется роль руководителя или администратора",
        )
    return current_user


async def forbid_production_roles(
    request: Request, db: AsyncSession = Depends(get_db)
) -> None:
    """Зависимость роутера: 403 сотруднику отдела производства работ.

    Аутентификацию не решает: нет токена или он недействителен — пропускает,
    ответит сама ручка (калькулятор без токена работает как прежде). Токен —
    из заголовка или `?token=` (скачивания идут ссылкой).

    Запрещает роль **из токена или из БД** — любая производственная. Токен
    живёт сутками: повышение до производства закрывает доступ сразу, обратное
    — после перелогина (безопасная сторона). Роль из БД читается колонкой, а не
    объектом: объект из identity map сессии мог бы быть устаревшим.
    """
    payload = decode_token_or_none(raw_token_from_request(request))
    if payload is None:
        return
    if is_production(payload.get("role")):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=PRODUCTION_FORBIDDEN_DETAIL)
    uid = current_user_id(payload)
    if uid is None:
        return
    db_role = (
        await db.execute(select(User.role).where(User.id == uid))
    ).scalar_one_or_none()
    if is_production(db_role):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=PRODUCTION_FORBIDDEN_DETAIL)
