import logging
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthCredentials
from sqlalchemy.orm import Session
from sqlalchemy import select
from db.models import User
from db.base import get_db
from web.config import settings

logger = logging.getLogger(__name__)
security = HTTPBearer()

class TokenData:
    def __init__(self, user_id: int):
        self.user_id = user_id

def create_access_token(user_id: int, expires_delta: Optional[timedelta] = None):
    """Создание JWT токена"""
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode = {"sub": str(user_id), "exp": expire}
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt

async def verify_token(
    credentials: HTTPAuthCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    """Проверка JWT токена"""
    token = credentials.credentials
    
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    
    stmt = select(User).where(User.id == int(user_id))
    user = db.execute(stmt).scalars().first()
    
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    
    return user

async def get_current_user(
    db: Session = Depends(get_db),
    credentials: Optional[HTTPAuthCredentials] = Depends(security)
) -> Optional[User]:
    """Получить текущего пользователя (опционально)"""
    if not credentials:
        return None
    
    try:
        return await verify_token(credentials, db)
    except:
        return None
