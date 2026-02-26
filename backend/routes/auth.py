from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from backend.auth import create_access_token, USER_PASSWORD, ADMIN_PASSWORD

router = APIRouter()

class LoginRequest(BaseModel):
    password: str

class LoginResponse(BaseModel):
    access_token: str
    token_type: str
    is_admin: bool

@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """Вход в систему с паролем"""
    
    if request.password == ADMIN_PASSWORD:
        token = create_access_token({"is_admin": True, "user_type": "admin"})
        return {
            "access_token": token,
            "token_type": "bearer",
            "is_admin": True
        }
    elif request.password == USER_PASSWORD:
        token = create_access_token({"is_admin": False, "user_type": "user"})
        return {
            "access_token": token,
            "token_type": "bearer",
            "is_admin": False
        }
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный пароль"
        )

@router.post("/logout")
async def logout():
    """Выход из системы"""
    return {"message": "Успешный выход"}
