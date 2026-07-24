from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import structlog

from app.database import get_db
from app.models.user import User
from app.utils.auth import verify_password, create_access_token, hash_password
from app.config import settings

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
    Authenticate. Два режима:
    - username+password → индивидуальный аккаунт (owner_id = user.id);
    - только password → legacy-вход по общему паролю роли (admin, затем user).
    """
    if not body.password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Пароль не может быть пустым",
        )

    if body.username:
        # Индивидуальный аккаунт по логину.
        result = await db.execute(select(User).where(User.username == body.username))
        user = result.scalar_one_or_none()
        if user and verify_password(body.password, user.password_hash):
            token = create_access_token(user.id, user.role, user.username)
            logger.info("User logged in", username=user.username, role=user.role)
            return LoginResponse(
                access_token=token, role=user.role, username=user.username, expires_in=86400,
            )
    else:
        # Legacy: общий пароль роли. Сначала admin, затем user.
        for role in ("admin", "user"):
            result = await db.execute(
                select(User).where(User.role == role, User.username.is_(None))
            )
            user = result.scalar_one_or_none()
            if user and verify_password(body.password, user.password_hash):
                token = create_access_token(user.id, role, None)
                logger.info("User logged in (shared)", role=role)
                return LoginResponse(
                    access_token=token, role=role, username=None, expires_in=86400,
                )

    logger.warning("Failed login attempt", has_username=bool(body.username))
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Неверный логин или пароль",
    )


async def init_users():
    """Initialize users table with default passwords on startup."""
    from app.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).limit(1))
        if result.scalar_one_or_none() is not None:
            return
        db.add(User(role="user", password_hash=hash_password(settings.USER_PASSWORD)))
        db.add(User(role="admin", password_hash=hash_password(settings.ADMIN_PASSWORD)))
        await db.commit()
        logger.info("Default users created")
