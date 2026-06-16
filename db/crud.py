import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from db.base import AsyncSessionLocal
from db.models import BotUser, BotPayment

logger = logging.getLogger(__name__)

# ---------- BotUser ----------
async def get_or_create_bot_user(
    session: AsyncSession,
    telegram_id: int,
    username: Optional[str] = None,
    email: Optional[str] = None
) -> BotUser:
    """Получить или создать пользователя. Вызывается только внутри переданной сессии."""
    result = await session.execute(
        select(BotUser).where(BotUser.telegram_id == telegram_id)
    )
    user = result.scalars().first()
    if not user:
        user = BotUser(
            telegram_id=telegram_id,
            username=username,
            email=email,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        session.add(user)
        # flush не обязателен, но можно для получения id
        await session.flush()
    return user

async def update_vpn_subscription(
    session: AsyncSession,
    telegram_id: int,
    days: int
) -> BotUser:
    """Обновляет VPN-подписку (продлевает или устанавливает) и возвращает пользователя."""
    user = await get_or_create_bot_user(session, telegram_id)
    now = datetime.now(timezone.utc)
    if user.vpn_subscription_end and user.vpn_subscription_end > now:
        user.vpn_subscription_end = user.vpn_subscription_end + timedelta(days=days)
    else:
        user.vpn_subscription_end = now + timedelta(days=days)
    user.updated_at = now
    return user

async def update_bypass_subscription(
    session: AsyncSession,
    telegram_id: int,
    days: int
) -> BotUser:
    user = await get_or_create_bot_user(session, telegram_id)
    now = datetime.now(timezone.utc)
    if user.bypass_subscription_end and user.bypass_subscription_end > now:
        user.bypass_subscription_end = user.bypass_subscription_end + timedelta(days=days)
    else:
        user.bypass_subscription_end = now + timedelta(days=days)
    user.updated_at = now
    return user

async def set_vpn_client_id(
    session: AsyncSession,
    telegram_id: int,
    client_uuid: Optional[str]
) -> None:
    user = await get_or_create_bot_user(session, telegram_id)
    user.vpn_client_id = client_uuid
    user.updated_at = datetime.now(timezone.utc)

async def set_vpn_server_id(
    session: AsyncSession,
    telegram_id: int,
    server_id: Optional[int]
) -> None:
    user = await get_or_create_bot_user(session, telegram_id)
    user.server_id = server_id
    user.updated_at = datetime.now(timezone.utc)

async def get_user_vpn_data(
    telegram_id: int
) -> Optional[dict]:
    """Возвращает словарь с данными пользователя (без объекта)."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(
                BotUser.vpn_subscription_end,
                BotUser.bypass_subscription_end,
                BotUser.vpn_client_id,
                BotUser.server_id
            ).where(BotUser.telegram_id == telegram_id)
        )
        row = result.first()
        if row:
            return {
                "vpn_subscription_end": row[0],
                "bypass_subscription_end": row[1],
                "vpn_client_id": row[2],
                "server_id": row[3]
            }
        return None

# ---------- BotPayment ----------
async def log_bot_payment(
    session: AsyncSession,
    payment_id: str,
    telegram_id: int
) -> bool:
    """Записывает платёж, возвращает False, если уже существует."""
    existing = await session.execute(
        select(BotPayment).where(BotPayment.payment_id == payment_id)
    )
    if existing.scalars().first():
        return False
    session.add(BotPayment(payment_id=payment_id, telegram_id=telegram_id))
    return True

async def is_bot_payment_processed(
    session: AsyncSession,
    payment_id: str
) -> bool:
    result = await session.execute(
        select(BotPayment).where(BotPayment.payment_id == payment_id)
    )
    return result.scalars().first() is not None

async def is_vpn_active(telegram_id: int) -> bool:
    """Проверяет, активна ли VPN-подписка у пользователя."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(BotUser.vpn_subscription_end).where(BotUser.telegram_id == telegram_id)
        )
        end_date = result.scalar()
        if end_date is None:
            return False
        return end_date > datetime.now(timezone.utc)

async def get_vpn_client_id(telegram_id: int) -> Optional[str]:
    """Возвращает vpn_client_id пользователя или None."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(BotUser.vpn_client_id).where(BotUser.telegram_id == telegram_id)
        )
        return result.scalar()