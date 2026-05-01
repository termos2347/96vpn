import logging
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session
from web.schemas.schemas import UserRegister, UserLogin, UserProfile
from web.services.auth import AuthService
from db.base import get_db
from web.security import create_access_token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])

@router.post("/register")
async def register(user_data: UserRegister, db: Session = Depends(get_db)):
    """Регистрация нового пользователя"""
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

@router.post("/login")
async def login(credentials: UserLogin, response: Response, db: Session = Depends(get_db)):
    """Вход пользователя – устанавливает HttpOnly cookie с JWT."""
    user = await AuthService.authenticate_user(
        db=db,
        email=credentials.email,
        password=credentials.password
    )
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    access_token = create_access_token(user_id=user.id)
    
    # Устанавливаем безопасную cookie
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,          # Недоступна из JavaScript
        secure=True,            # Передавать только по HTTPS (для разработки на localhost отключить)
        samesite="lax",
        max_age=2592000,        # 30 дней
        path="/"
    )
    
    return {
        "user_id": user.id,
        "is_active": user.is_active
    }

@router.post("/logout")
async def logout(response: Response):
    """Выход – удаляет cookie."""
    response.delete_cookie("access_token", path="/")
    return {"status": "ok"}

@router.get("/profile/{user_id}", response_model=UserProfile)
async def get_profile(user_id: int, db: Session = Depends(get_db)):
    """Получить профиль пользователя"""
    user = await AuthService.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user