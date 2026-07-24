from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import bcrypt
from jose import JWTError, jwt
from app.config import settings
import structlog

logger = structlog.get_logger()

bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode(), hashed_password.encode())


def create_access_token(user_id: int, role: str, username: Optional[str] = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=settings.JWT_EXPIRE_HOURS)
    payload = {
        "sub": str(user_id),   # sub = идентификатор человека (для owner_id)
        "role": role,
        "username": username,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def current_user_id(current_user: dict) -> Optional[int]:
    """owner_id из токена. None для legacy-токенов, где sub был ролью (не число)."""
    sub = current_user.get("sub")
    if sub is not None and str(sub).isdigit():
        return int(sub)
    return None


def verify_token(token: str) -> dict:
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )
        return payload
    except JWTError as e:
        logger.warning("Token verification failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Недействительный или истёкший токен",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> dict:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется авторизация",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return verify_token(credentials.credentials)


async def get_download_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    token: Optional[str] = Query(None),
) -> dict:
    """Auth for file download endpoints: accepts Bearer header or ?token= query param.
    Query param support is needed because browsers block a.click() after async requests."""
    raw_token = credentials.credentials if credentials else token
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется авторизация",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return verify_token(raw_token)


async def get_admin_user(
    current_user: dict = Depends(get_current_user),
) -> dict:
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Недостаточно прав. Требуется роль администратора",
        )
    return current_user
