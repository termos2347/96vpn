import logging
import secrets
import re
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
import bcrypt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from config import settings
from db.models import WebUser
from db.crud import get_prompts_data, get_prompt_by_id as get_p, get_all_categories

logger = logging.getLogger(__name__)

# ========== Хеширование паролей ==========
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(plain_password: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed.encode('utf-8'))

def validate_password_strength(password: str) -> bool:
    """Проверяет сложность пароля: минимум 8 символов, только латиница и цифры."""
    if len(password) < 8:
        return False
    if not re.match(r'^[a-zA-Z0-9]+$', password):
        return False
    return True

# ========== Кэш промптов ==========
_cached_data: Optional[Dict[str, Any]] = None
_cache_valid = False


class AuthService:
    @staticmethod
    async def create_user(db: AsyncSession, email: str, password: str, username: Optional[str] = None, source: str = "web") -> Optional[WebUser]:
        # Серверная валидация пароля
        if not validate_password_strength(password):
            logger.warning(f"Password validation failed for email {email}")
            return None

        stmt = select(WebUser).where(WebUser.email == email)
        result = await db.execute(stmt)
        existing = result.scalars().first()
        if existing:
            logger.warning(f"User with email {email} already exists")
            return None

        hashed = hash_password(password)

        user = WebUser(
            email=email,
            username=username,
            hashed_password=hashed,
            is_active=False,
            expiry_date=None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        logger.info(f"Created user {user.id} with email {email}")
        return user

    @staticmethod
    async def authenticate_user(db: AsyncSession, email: str, password: str) -> Optional[WebUser]:
        stmt = select(WebUser).where(WebUser.email == email)
        result = await db.execute(stmt)
        user = result.scalars().first()
        if not user:
            return None
        if not user.hashed_password:
            return None
        if not verify_password(password, user.hashed_password):
            return None
        return user

    @staticmethod
    async def get_user_by_id(db: AsyncSession, user_id: int) -> Optional[WebUser]:
        stmt = select(WebUser).where(WebUser.id == user_id)
        result = await db.execute(stmt)
        return result.scalars().first()

    @staticmethod
    async def get_user_by_email(db: AsyncSession, email: str) -> Optional[WebUser]:
        stmt = select(WebUser).where(WebUser.email == email)
        result = await db.execute(stmt)
        return result.scalars().first()

    @staticmethod
    async def create_reset_token(db: AsyncSession, email: str) -> Optional[str]:
        stmt = select(WebUser).where(WebUser.email == email)
        result = await db.execute(stmt)
        user = result.scalars().first()
        if not user:
            return None
        token = secrets.token_urlsafe(32)
        user.reset_token = token
        user.reset_token_expires = datetime.now(timezone.utc) + timedelta(hours=1)
        await db.commit()
        return token

    @staticmethod
    async def reset_password(db: AsyncSession, token: str, new_password: str) -> bool:
        if not validate_password_strength(new_password):
            logger.warning("Reset password: weak password rejected")
            return False
        stmt = select(WebUser).where(WebUser.reset_token == token)
        result = await db.execute(stmt)
        user = result.scalars().first()
        if not user or user.reset_token_expires is None or user.reset_token_expires < datetime.now(timezone.utc):
            return False
        user.hashed_password = hash_password(new_password)
        user.reset_token = None
        user.reset_token_expires = None
        await db.commit()
        return True


class SubscriptionService:
    @staticmethod
    async def activate_subscription(db: AsyncSession, user: WebUser, days: int = 30) -> bool:
        now = datetime.now(timezone.utc)
        user.expiry_date = now + timedelta(days=days)
        user.is_active = True
        await db.commit()
        logger.info(f"Subscription activated for user {user.id}, expires at {user.expiry_date}")
        return True

    @staticmethod
    async def renew_subscription(db: AsyncSession, user: WebUser, days: int = 30) -> bool:
        now = datetime.now(timezone.utc)
        if user.expiry_date and user.expiry_date > now:
            new_expiry = user.expiry_date + timedelta(days=days)
        else:
            new_expiry = now + timedelta(days=days)
        user.expiry_date = new_expiry
        user.is_active = True
        await db.commit()
        logger.info(f"Subscription renewed for user {user.id}, new expiry {new_expiry}")
        return True

    @staticmethod
    def get_days_remaining(user: WebUser) -> Optional[int]:
        if not user.expiry_date:
            return None
        remaining = (user.expiry_date - datetime.now(timezone.utc)).days
        return max(0, remaining)

    @staticmethod
    async def check_and_deactivate_expired(db: AsyncSession) -> int:
        now = datetime.now(timezone.utc)
        stmt = select(WebUser).where(WebUser.is_active == True, WebUser.expiry_date < now)
        result = await db.execute(stmt)
        expired_users = result.scalars().all()
        for user in expired_users:
            user.is_active = False
            logger.info(f"User {user.id} deactivated due to expired subscription")
        await db.commit()
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
        global _cached_data, _cache_valid
        if not _cache_valid or _cached_data is None:
            logger.info("Preloading prompts data at startup...")
            _cached_data = await get_prompts_data()
            _cache_valid = True
            logger.info("Prompts cache initialized")