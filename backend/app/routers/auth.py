from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import structlog

from app.database import get_db
from app.models.user import User
from app.utils.auth import verify_password, create_access_token

logger = structlog.get_logger()

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    password: str
    username: Optional[str] = None   # None → legacy-вход по общему паролю роли


class LoginResponse(BaseModel):
    access_token: str
    role: str
    username: Optional[str] = None
    expires_in: int


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """
    Authenticate по индивидуальному аккаунту (username + password, owner_id = user.id).
    Вход по общим паролям ролей удалён — только персональные аккаунты.
    Деактивированный аккаунт (is_active=false) войти не может.
    """
    if not body.username or not body.password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Введите логин и пароль",
        )

    result = await db.execute(select(User).where(User.username == body.username))
    user = result.scalar_one_or_none()
    if user and user.is_active and verify_password(body.password, user.password_hash):
        token = create_access_token(user.id, user.role, user.username)
        logger.info("User logged in", username=user.username, role=user.role)
        return LoginResponse(
            access_token=token, role=user.role, username=user.username, expires_in=86400,
        )

    logger.warning("Failed login attempt", username=body.username)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Неверный логин или пароль",
    )
