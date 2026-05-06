import logging
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from sqlalchemy.orm import Session
from sqlalchemy import select
from passlib.context import CryptContext
from db.models import WebUser
from config import settings
from db.crud import get_prompts_data, get_prompt_by_id as get_p, get_all_categories

logger = logging.getLogger(__name__)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ========== In‑memory кэш ==========
_cached_data: Optional[Dict[str, Any]] = None
_cache_valid = False


class AuthService:
    """Сервис аутентификации и управления пользователями"""

    @staticmethod
    async def create_user(db: Session, email: str, password: str, username: Optional[str] = None, source: str = "web") -> Optional[WebUser]:
        stmt = select(WebUser).where(WebUser.email == email)
        existing = db.execute(stmt).scalars().first()
        if existing:
            logger.warning(f"User with email {email} already exists")
            return None

        hashed = pwd_context.hash(password)

        user = WebUser(
            email=email,
            username=username,
            hashed_password=hashed,
            is_active=False,
            expiry_date=None,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        logger.info(f"Created user {user.id} with email {email}")
        return user

    @staticmethod
    async def authenticate_user(db: Session, email: str, password: str) -> Optional[WebUser]:
        stmt = select(WebUser).where(WebUser.email == email)
        user = db.execute(stmt).scalars().first()
        if not user:
            return None
        if not user.hashed_password:
            return None
        if not pwd_context.verify(password, user.hashed_password):
            return None
        return user

    @staticmethod
    async def get_user_by_id(db: Session, user_id: int) -> Optional[WebUser]:
        stmt = select(WebUser).where(WebUser.id == user_id)
        return db.execute(stmt).scalars().first()

    @staticmethod
    async def get_user_by_email(db: Session, email: str) -> Optional[WebUser]:
        stmt = select(WebUser).where(WebUser.email == email)
        return db.execute(stmt).scalars().first()

    @staticmethod
    async def create_reset_token(db: Session, email: str) -> Optional[str]:
        stmt = select(WebUser).where(WebUser.email == email)
        user = db.execute(stmt).scalars().first()
        if not user:
            return None
        token = secrets.token_urlsafe(32)
        user.reset_token = token
        user.reset_token_expires = datetime.utcnow() + timedelta(hours=1)
        db.commit()
        return token

    @staticmethod
    async def reset_password(db: Session, token: str, new_password: str) -> bool:
        stmt = select(WebUser).where(WebUser.reset_token == token)
        user = db.execute(stmt).scalars().first()
        if not user or user.reset_token_expires is None or user.reset_token_expires < datetime.utcnow():
            return False
        user.hashed_password = pwd_context.hash(new_password)
        user.reset_token = None
        user.reset_token_expires = None
        db.commit()
        return True


class SubscriptionService:
    @staticmethod
    async def activate_subscription(db: Session, user: WebUser, days: int = 30) -> bool:
        now = datetime.utcnow()
        user.expiry_date = now + timedelta(days=days)
        user.is_active = True
        db.commit()
        logger.info(f"Subscription activated for user {user.id}, expires at {user.expiry_date}")
        return True

    @staticmethod
    async def renew_subscription(db: Session, user: WebUser, days: int = 30) -> bool:
        now = datetime.utcnow()
        if user.expiry_date and user.expiry_date > now:
            new_expiry = user.expiry_date + timedelta(days=days)
        else:
            new_expiry = now + timedelta(days=days)
        user.expiry_date = new_expiry
        user.is_active = True
        db.commit()
        logger.info(f"Subscription renewed for user {user.id}, new expiry {new_expiry}")
        return True

    @staticmethod
    def get_days_remaining(user: WebUser) -> Optional[int]:
        if not user.expiry_date:
            return None
        remaining = (user.expiry_date - datetime.utcnow()).days
        return max(0, remaining)

    @staticmethod
    async def check_and_deactivate_expired(db: Session):
        now = datetime.utcnow()
        stmt = select(WebUser).where(WebUser.is_active == True, WebUser.expiry_date < now)
        expired_users = db.execute(stmt).scalars().all()
        for user in expired_users:
            user.is_active = False
            logger.info(f"User {user.id} deactivated due to expired subscription")
        db.commit()
        return len(expired_users)


class PromptService:
    @staticmethod
    async def get_prompts_data():
        global _cached_data, _cache_valid
        if not _cache_valid or _cached_data is None:
            logger.info("Loading prompts data from database...")
            _cached_data = await get_prompts_data()
            _cache_valid = True
        return _cached_data

    @staticmethod
    async def get_prompt_by_id(prompt_id: int):
        return await get_p(prompt_id)

    @staticmethod
    async def get_categories():
        data = await PromptService.get_prompts_data()
        return data["categories"]

    @staticmethod
    def invalidate():
        global _cache_valid
        _cache_valid = False
        logger.info("Prompts cache invalidated")
        
    @staticmethod
    async def init_cache():
        """Принудительно загружает кэш при старте приложения."""
        global _cached_data, _cache_valid
        if not _cache_valid or _cached_data is None:
            logger.info("Preloading prompts data at startup...")
            _cached_data = await get_prompts_data()
            _cache_valid = True
            logger.info("Prompts cache initialized")