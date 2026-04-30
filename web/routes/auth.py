# web/routes/auth.py (исправленная версия)
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
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # После регистрации не активируем подписку – требуется оплата
    return {
        "id": user.id,
        "email": user.email,
        "message": "Registration successful. Please proceed to payment."
    }

@router.post("/login")
async def login(credentials: UserLogin, db: Session = Depends(get_db)):
    """Вход пользователя – возвращает JWT токен"""
    user = await AuthService.authenticate_user(
        db=db,
        email=credentials.email,
        password=credentials.password
    )
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Создаём JWT токен
    access_token = create_access_token(user_id=user.id)
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user_id": user.id,
        "is_active": user.is_active
    }

@router.get("/profile/{user_id}", response_model=UserProfile)
async def get_profile(user_id: int, db: Session = Depends(get_db)):
    """Получить профиль пользователя"""
    user = await AuthService.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user