"""CRUD операции для работы с пользователями и подписками."""
import logging
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from db.base import AsyncSessionLocal
from db.models import User

logger = logging.getLogger(__name__)


async def get_or_create_user(
    user_id: int,
    username: Optional[str] = None,
    email: Optional[str] = None,
    session: Optional[AsyncSession] = None
) -> Optional[User]:
    """Получить или создать пользователя."""
    if session is None:
        async with AsyncSessionLocal() as session:
            return await _get_or_create_user(session, user_id, username, email)
    else:
        return await _get_or_create_user(session, user_id, username, email)


async def _get_or_create_user(session: AsyncSession, user_id: int, username: Optional[str], email: Optional[str]) -> User:
    result = await session.execute(select(User).where(User.user_id == user_id))
    user = result.scalars().first()
    if not user:
        user = User(
            user_id=user_id,
            username=username,
            email=email,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
    return user


async def set_vpn_subscription(user_id: int, days: int) -> None:
    """Установить или продлить VPN-подписку."""
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(user_id, session=session)
        now = datetime.utcnow()
        if user.vpn_subscription_end and user.vpn_subscription_end > now:
            # Продление
            user.vpn_subscription_end = user.vpn_subscription_end + timedelta(days=days)
        else:
            user.vpn_subscription_end = now + timedelta(days=days)
        user.updated_at = now
        await session.commit()
        logger.info(f"VPN subscription set for user {user_id} until {user.vpn_subscription_end}")


async def set_bypass_subscription(user_id: int, days: int) -> None:
    """Установить или продлить обход DPI."""
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(user_id, session=session)
        now = datetime.utcnow()
        if user.bypass_subscription_end and user.bypass_subscription_end > now:
            user.bypass_subscription_end = user.bypass_subscription_end + timedelta(days=days)
        else:
            user.bypass_subscription_end = now + timedelta(days=days)
        user.updated_at = now
        await session.commit()
        logger.info(f"Bypass subscription set for user {user_id} until {user.bypass_subscription_end}")


async def set_vpn_client_id(user_id: int, client_uuid: Optional[str]) -> None:
    """Установить или очистить VPN client ID."""
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(user_id, session=session)
        user.vpn_client_id = client_uuid
        user.updated_at = datetime.utcnow()
        await session.commit()


async def get_vpn_end(user_id: int) -> Optional[datetime]:
    """Возвращает дату окончания VPN-подписки."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User.vpn_subscription_end).where(User.user_id == user_id))
        return result.scalar()


async def get_bypass_end(user_id: int) -> Optional[datetime]:
    """Возвращает дату окончания обхода DPI."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User.bypass_subscription_end).where(User.user_id == user_id))
        return result.scalar()


async def is_vpn_active(user_id: int) -> bool:
    """Активна ли VPN-подписка."""
    end = await get_vpn_end(user_id)
    if end and end > datetime.utcnow():
        return True
    return False


async def is_bypass_active(user_id: int) -> bool:
    """Активен ли обход DPI."""
    end = await get_bypass_end(user_id)
    if end and end > datetime.utcnow():
        return True
    return False


async def get_vpn_client_id(user_id: int) -> Optional[str]:
    """Получить VPN client ID."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User.vpn_client_id).where(User.user_id == user_id))
        return result.scalar()