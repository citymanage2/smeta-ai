"""Управление аккаунтами сотрудников (только для админа).

CRUD персональных аккаунтов: создать, сменить роль/ФИО, деактивировать,
сбросить пароль. Удаление — soft (is_active=false), чтобы не осиротить
owner_id проектов/задач.
"""
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.utils.auth import get_admin_user, hash_password
from app.utils.permissions import ASSIGNABLE_ROLES, ROLE_ADMIN, get_manager_user

logger = structlog.get_logger()

router = APIRouter(prefix="/admin/users", tags=["admin-users"])


# --- Pydantic ---

class UserCreate(BaseModel):
    username: str
    password: str
    role: str
    full_name: Optional[str] = None

    @field_validator("username")
    @classmethod
    def _username_nonempty(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("Логин не может быть пустым")
        return v

    @field_validator("password")
    @classmethod
    def _password_len(cls, v: str) -> str:
        if not v or len(v) < 4:
            raise ValueError("Пароль не короче 4 символов")
        return v

    @field_validator("role")
    @classmethod
    def _role_valid(cls, v: str) -> str:
        if v not in ASSIGNABLE_ROLES:
            raise ValueError(f"Недопустимая роль: {v}")
        return v


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None

    @field_validator("role")
    @classmethod
    def _role_valid(cls, v):
        if v is not None and v not in ASSIGNABLE_ROLES:
            raise ValueError(f"Недопустимая роль: {v}")
        return v


class PasswordReset(BaseModel):
    password: str

    @field_validator("password")
    @classmethod
    def _password_len(cls, v: str) -> str:
        if not v or len(v) < 4:
            raise ValueError("Пароль не короче 4 символов")
        return v


class UserResponse(BaseModel):
    id: int
    username: Optional[str]
    full_name: Optional[str]
    role: str
    is_active: bool
    created_at: str


def _to_response(u: User) -> UserResponse:
    return UserResponse(
        id=u.id,
        username=u.username,
        full_name=u.full_name,
        role=u.role,
        is_active=u.is_active,
        created_at=u.created_at.isoformat() if u.created_at else "",
    )


async def _count_active_admins(db: AsyncSession) -> int:
    # Только реальные аккаунты (с логином); legacy shared-записи (username NULL) не в счёт.
    return (
        await db.execute(
            select(func.count(User.id)).where(
                User.role == ROLE_ADMIN,
                User.is_active.is_(True),
                User.username.is_not(None),
            )
        )
    ).scalar_one()


async def _get_user_or_404(user_id: int, db: AsyncSession) -> User:
    user = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")
    return user


# --- Endpoints ---

class AssignableUser(BaseModel):
    id: int
    display_name: str
    role: str


@router.get("/assignable", response_model=list[AssignableUser])
async def list_assignable_users(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_manager_user),
):
    """Активные сотрудники для выпадашки переназначения владельца (менеджер/админ)."""
    rows = (
        await db.execute(
            select(User)
            .where(User.username.is_not(None), User.is_active.is_(True))
            .order_by(User.full_name, User.username)
        )
    ).scalars().all()
    return [
        AssignableUser(id=u.id, display_name=(u.full_name or u.username or f"#{u.id}"), role=u.role)
        for u in rows
    ]


@router.get("", response_model=list[UserResponse])
async def list_users(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_admin_user),
):
    """Список персональных аккаунтов (без legacy shared-записей с username IS NULL)."""
    rows = (
        await db.execute(
            select(User).where(User.username.is_not(None)).order_by(User.created_at.asc())
        )
    ).scalars().all()
    return [_to_response(u) for u in rows]


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_admin_user),
):
    existing = (
        await db.execute(select(User).where(User.username == body.username))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Пользователь с таким логином уже существует",
        )
    user = User(
        username=body.username,
        full_name=body.full_name,
        role=body.role,
        is_active=True,
        password_hash=hash_password(body.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    logger.info("User account created", username=user.username, role=user.role)
    return _to_response(user)


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    body: UserUpdate,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_admin_user),
):
    user = await _get_user_or_404(user_id, db)

    # Защита последнего активного админа: нельзя разжаловать/деактивировать,
    # если он единственный активный админ.
    demoting = body.role is not None and body.role != ROLE_ADMIN and user.role == ROLE_ADMIN
    deactivating = body.is_active is False and user.is_active
    if (demoting or deactivating) and user.role == ROLE_ADMIN:
        if await _count_active_admins(db) <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Нельзя убрать роль/деактивировать последнего активного администратора",
            )

    if body.full_name is not None:
        user.full_name = body.full_name
    if body.role is not None:
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active
    await db.commit()
    await db.refresh(user)
    logger.info("User account updated", user_id=user_id, role=user.role, is_active=user.is_active)
    return _to_response(user)


@router.post("/{user_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    user_id: int,
    body: PasswordReset,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_admin_user),
):
    user = await _get_user_or_404(user_id, db)
    user.password_hash = hash_password(body.password)
    await db.commit()
    logger.info("User password reset", user_id=user_id)
