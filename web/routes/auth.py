import logging
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, EmailStr
from web.schemas.schemas import UserRegister, UserLogin, UserProfile
from web.services.auth import AuthService
from db.base import AsyncSession, get_async_db,  AsyncSessionLocal
from web.security import create_access_token
from config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])

# ---------- Регистрация ----------
@router.post("/register")
async def register(user_data: UserRegister, db: AsyncSession = Depends(get_async_db)):
    user = await AuthService.create_user(
        db=db,
        email=user_data.email,
        password=user_data.password,
        username=user_data.username,
        source="web"
    )
    if not user:
        raise HTTPException(status_code=400, detail="Пользователь с таким email уже зарегистрирован")
    return {
        "id": user.id,
        "email": user.email,
        "message": "Registration successful. Please proceed to payment."
    }

# ---------- Вход ----------
@router.post("/login")
async def login(credentials: UserLogin, response: Response, db: AsyncSession = Depends(get_async_db)):
    user = await AuthService.authenticate_user(db, credentials.email, credentials.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    access_token = create_access_token(user_id=user.id)
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=True,            # для разработки на localhost можно False
        samesite="lax",
        max_age=2592000,        # 30 дней
        path="/"
    )
    return {
        "user_id": user.id,
        "is_active": user.is_active
    }

# ---------- Выход ----------
@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("access_token", path="/")
    return {"status": "ok"}

# ---------- Профиль ----------
@router.get("/profile/{user_id}", response_model=UserProfile)
async def get_profile(user_id: int, db: AsyncSession = Depends(get_async_db)):
    user = await AuthService.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

# ---------- Восстановление пароля ----------
class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

@router.post("/forgot-password")
async def forgot_password(data: ForgotPasswordRequest, db: AsyncSession = Depends(get_async_db)):
    token = await AuthService.create_reset_token(db, data.email)
    if token:
        reset_url = f"{settings.SITE_URL}/reset-password?token={token}"
        logger.info(f"Password reset link for {data.email}: {reset_url}")
        # В будущем здесь будет отправка email
    return {"message": "Если указанный email зарегистрирован, ссылка для сброса отправлена."}

@router.post("/reset-password")
async def reset_password(data: ResetPasswordRequest, db: AsyncSession = Depends(get_async_db)):
    success = await AuthService.reset_password(db, data.token, data.new_password)
    if not success:
        raise HTTPException(status_code=400, detail="Недействительный или истекший токен.")
    return {"message": "Пароль успешно изменён."}