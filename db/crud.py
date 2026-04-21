import logging
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from .base import AsyncSessionLocal
from .models import User
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

async def get_or_create_user(user_id: int, username: str = None):
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(select(User).where(User.user_id == user_id))
            user = result.scalar_one_or_none()
            if not user:
                user = User(user_id=user_id, username=username)
                session.add(user)
                await session.commit()
                await session.refresh(user)
            elif username and user.username != username:
                user.username = username
                await session.commit()
            return user
        except IntegrityError as e:
            await session.rollback()
            logger.warning(f"IntegrityError in get_or_create_user (user_id={user_id}), retrying fetch: {e}")
            # Повторно получаем пользователя (мог быть создан в параллельной сессии)
            result = await session.execute(select(User).where(User.user_id == user_id))
            return result.scalar_one_or_none()
        except Exception as e:
            await session.rollback()
            logger.error(f"Unexpected error in get_or_create_user: {e}", exc_info=True)
            raise

async def set_vpn_subscription(user_id: int, days: int):
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(select(User).where(User.user_id == user_id))
            user = result.scalar_one_or_none()
            if not user:
                user = User(user_id=user_id)
                session.add(user)
                await session.flush()
            
            now = datetime.now()
            if user.vpn_subscription_end and user.vpn_subscription_end > now:
                base_date = user.vpn_subscription_end
            else:
                base_date = now
            
            new_end = base_date + timedelta(days=days)
            user.vpn_subscription_end = new_end
            await session.commit()
            logger.info(f"VPN subscription extended for user {user_id} by {days} days, new end: {new_end}")
            return True
        except IntegrityError as e:
            await session.rollback()
            logger.error(f"IntegrityError in set_vpn_subscription for user {user_id}: {e}")
            # Если IntegrityError из-за дубля user_id, пробуем ещё раз получить и обновить
            return await _retry_set_vpn(user_id, days)
        except Exception as e:
            await session.rollback()
            logger.error(f"Error in set_vpn_subscription: {e}", exc_info=True)
            raise

async def _retry_set_vpn(user_id: int, days: int):
    """Вспомогательная функция для повторной попытки при гонке создания пользователя."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.user_id == user_id))
        user = result.scalar_one()
        now = datetime.now()
        if user.vpn_subscription_end and user.vpn_subscription_end > now:
            base_date = user.vpn_subscription_end
        else:
            base_date = now
        new_end = base_date + timedelta(days=days)
        user.vpn_subscription_end = new_end
        await session.commit()
        return True

async def is_vpn_active(user_id: int) -> bool:
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(select(User).where(User.user_id == user_id))
            user = result.scalar_one_or_none()
            if user and user.vpn_subscription_end:
                return user.vpn_subscription_end > datetime.now()
            return False
        except Exception as e:
            logger.error(f"Error in is_vpn_active: {e}", exc_info=True)
            return False

async def get_vpn_end(user_id: int):
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(select(User).where(User.user_id == user_id))
            user = result.scalar_one_or_none()
            return user.vpn_subscription_end if user else None
        except Exception as e:
            logger.error(f"Error in get_vpn_end: {e}", exc_info=True)
            return None

# Аналогично для bypass функций
async def set_bypass_subscription(user_id: int, days: int):
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(select(User).where(User.user_id == user_id))
            user = result.scalar_one_or_none()
            if not user:
                user = User(user_id=user_id)
                session.add(user)
                await session.flush()
            
            now = datetime.now()
            if user.bypass_subscription_end and user.bypass_subscription_end > now:
                base_date = user.bypass_subscription_end
            else:
                base_date = now
            
            new_end = base_date + timedelta(days=days)
            user.bypass_subscription_end = new_end
            await session.commit()
            logger.info(f"Bypass subscription extended for user {user_id} by {days} days, new end: {new_end}")
            return True
        except IntegrityError as e:
            await session.rollback()
            logger.error(f"IntegrityError in set_bypass_subscription for user {user_id}: {e}")
            return await _retry_set_bypass(user_id, days)
        except Exception as e:
            await session.rollback()
            logger.error(f"Error in set_bypass_subscription: {e}", exc_info=True)
            raise

async def _retry_set_bypass(user_id: int, days: int):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.user_id == user_id))
        user = result.scalar_one()
        now = datetime.now()
        if user.bypass_subscription_end and user.bypass_subscription_end > now:
            base_date = user.bypass_subscription_end
        else:
            base_date = now
        new_end = base_date + timedelta(days=days)
        user.bypass_subscription_end = new_end
        await session.commit()
        return True

async def is_bypass_active(user_id: int) -> bool:
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(select(User).where(User.user_id == user_id))
            user = result.scalar_one_or_none()
            if user and user.bypass_subscription_end:
                return user.bypass_subscription_end > datetime.now()
            return False
        except Exception as e:
            logger.error(f"Error in is_bypass_active: {e}", exc_info=True)
            return False

async def get_bypass_end(user_id: int):
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(select(User).where(User.user_id == user_id))
            user = result.scalar_one_or_none()
            return user.bypass_subscription_end if user else None
        except Exception as e:
            logger.error(f"Error in get_bypass_end: {e}", exc_info=True)
            return None
        
async def set_vpn_client_id(user_id: int, client_id: str) -> bool:
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(select(User).where(User.user_id == user_id))
            user = result.scalar_one_or_none()
            if user:
                user.vpn_client_id = client_id
                await session.commit()
                return True
            return False
        except Exception as e:
            logger.error(f"Error in set_vpn_client_id: {e}", exc_info=True)
            return False

async def get_vpn_client_id(user_id: int) -> str | None:
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(select(User).where(User.user_id == user_id))
            user = result.scalar_one_or_none()
            return user.vpn_client_id if user else None
        except Exception as e:
            logger.error(f"Error in get_vpn_client_id: {e}", exc_info=True)
            return None