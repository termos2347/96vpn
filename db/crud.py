from sqlalchemy import select
from .base import AsyncSessionLocal
from .models import User
from datetime import datetime, timedelta

async def get_or_create_user(user_id: int, username: str = None):
    async with AsyncSessionLocal() as session:
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

# === VPN подписка ===
async def set_vpn_subscription(user_id: int, days: int):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.user_id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            user = User(user_id=user_id)
            session.add(user)
            await session.flush()
        new_end = datetime.now() + timedelta(days=days)
        user.vpn_subscription_end = new_end
        await session.commit()
        return True

async def is_vpn_active(user_id: int) -> bool:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.user_id == user_id))
        user = result.scalar_one_or_none()
        if user and user.vpn_subscription_end:
            return user.vpn_subscription_end > datetime.now()
        return False

async def get_vpn_end(user_id: int):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.user_id == user_id))
        user = result.scalar_one_or_none()
        return user.vpn_subscription_end if user else None

# === Bypass (обход) подписка ===
async def set_bypass_subscription(user_id: int, days: int):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.user_id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            user = User(user_id=user_id)
            session.add(user)
            await session.flush()
        new_end = datetime.now() + timedelta(days=days)
        user.bypass_subscription_end = new_end
        await session.commit()
        return True

async def is_bypass_active(user_id: int) -> bool:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.user_id == user_id))
        user = result.scalar_one_or_none()
        if user and user.bypass_subscription_end:
            return user.bypass_subscription_end > datetime.now()
        return False

async def get_bypass_end(user_id: int):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.user_id == user_id))
        user = result.scalar_one_or_none()
        return user.bypass_subscription_end if user else None