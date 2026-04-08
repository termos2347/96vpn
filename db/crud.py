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

async def set_subscription(user_id: int, days: int):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.user_id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            user = User(user_id=user_id)
            session.add(user)
            await session.flush()
        new_end = datetime.now() + timedelta(days=days)
        user.subscription_end = new_end
        await session.commit()
        print(f"[DB] Subscription set for {user_id}: {new_end}")
        return True

async def is_subscription_active(user_id: int) -> bool:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.user_id == user_id))
        user = result.scalar_one_or_none()
        if user and user.subscription_end:
            return user.subscription_end > datetime.now()
        return False

async def get_subscription_end(user_id: int):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.user_id == user_id))
        user = result.scalar_one_or_none()
        return user.subscription_end if user else None