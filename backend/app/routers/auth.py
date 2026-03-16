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


class LoginResponse(BaseModel):
    access_token: str
    role: str
    expires_in: int


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """
    Authenticate with password. Returns JWT token and role.
    Tries both 'user' and 'admin' roles.
    """
    if not body.password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Пароль не может быть пустым",
        )

    # Try admin first, then user
    for role in ("admin", "user"):
        result = await db.execute(select(User).where(User.role == role))
        user = result.scalar_one_or_none()

        if user and verify_password(body.password, user.password_hash):
            token = create_access_token(role)
            logger.info("User logged in", role=role)
            return LoginResponse(
                access_token=token,
                role=role,
                expires_in=86400,
            )

    logger.warning("Failed login attempt")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Неверный пароль",
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
