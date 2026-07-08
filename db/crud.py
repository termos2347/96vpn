import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import BotUser, BotPayment
from config import settings

logger = logging.getLogger(__name__)


async def get_or_create_bot_user(
    session: AsyncSession,
    telegram_id: int,
    username: Optional[str] = None,
    email: Optional[str] = None,
) -> BotUser:
    stmt = select(BotUser).where(BotUser.telegram_id == telegram_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        user = BotUser(
            telegram_id=telegram_id,
            username=username,
            email=email,
        )
        session.add(user)
        await session.flush()
        logger.info(f"Created new user with telegram_id={telegram_id}")
    else:
        if username is not None and user.username != username:
            user.username = username
        if email is not None and user.email != email:
            user.email = email

    return user


async def activate_subscription(
    session: AsyncSession,
    telegram_id: int,
    product_type: str,
    period: str,
    payment_id: Optional[str] = None,
    user: Optional[BotUser] = None,
) -> bool:
    if product_type not in ("vpn", "bypass"):
        logger.error(f"Invalid product_type: {product_type}")
        return False

    if period not in settings.PERIOD_DAYS:
        logger.error(f"Invalid period: {period}")
        return False

    if user is None:
        user = await get_or_create_bot_user(session, telegram_id)

    days = settings.PERIOD_DAYS[period]
    now = datetime.now(timezone.utc)

    if product_type == "vpn":
        if user.vpn_subscription_end and user.vpn_subscription_end > now:
            new_end = user.vpn_subscription_end + timedelta(days=days)
        else:
            new_end = now + timedelta(days=days)
        user.vpn_subscription_end = new_end
        logger.info(f"VPN subscription activated for {telegram_id} until {new_end}")

    elif product_type == "bypass":
        if user.bypass_subscription_end and user.bypass_subscription_end > now:
            new_end = user.bypass_subscription_end + timedelta(days=days)
        else:
            new_end = now + timedelta(days=days)
        user.bypass_subscription_end = new_end
        logger.info(f"Bypass subscription activated for {telegram_id} until {new_end}")

    if payment_id:
        stmt = select(BotPayment).where(BotPayment.payment_id == payment_id)
        result = await session.execute(stmt)
        payment = result.scalar_one_or_none()
        if payment:
            payment.is_paid = True
            payment.status = "succeeded"
            payment.updated_at = now
            logger.info(f"Payment {payment_id} marked as paid")

    return True


async def create_payment_record(
    session: AsyncSession,
    payment_id: str,
    telegram_id: int,
    amount: float,
    currency: str = "RUB",
) -> BotPayment:
    now = datetime.now(timezone.utc)
    payment = BotPayment(
        payment_id=payment_id,
        telegram_id=telegram_id,
        amount=amount,
        currency=currency,
        status="pending",
        is_paid=False,
        created_at=now,
        updated_at=now,
    )
    session.add(payment)
    await session.flush()
    logger.info(f"Payment record created: {payment_id}")
    return payment


async def get_payment_by_id(session: AsyncSession, payment_id: str) -> Optional[BotPayment]:
    stmt = select(BotPayment).where(BotPayment.payment_id == payment_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_user_by_telegram_id(session: AsyncSession, telegram_id: int) -> Optional[BotUser]:
    stmt = select(BotUser).where(BotUser.telegram_id == telegram_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def update_user_vpn_client(
    session: AsyncSession,
    telegram_id: int,
    client_id: str,
) -> bool:
    user = await get_user_by_telegram_id(session, telegram_id)
    if not user:
        logger.error(f"User {telegram_id} not found")
        return False
    user.vpn_client_id = client_id
    logger.info(f"Updated vpn_client_id for {telegram_id}: {client_id}")
    return True


async def clear_user_vpn_client(session: AsyncSession, telegram_id: int) -> bool:
    user = await get_user_by_telegram_id(session, telegram_id)
    if not user:
        logger.error(f"User {telegram_id} not found")
        return False
    user.vpn_client_id = None
    logger.info(f"Cleared vpn_client_id for {telegram_id}")
    return True


async def get_expired_users(session: AsyncSession) -> list[BotUser]:
    now = datetime.now(timezone.utc)
    stmt = select(BotUser).where(
        and_(
            BotUser.vpn_subscription_end < now,
            BotUser.vpn_client_id.isnot(None),
        )
    )
    result = await session.execute(stmt)
    return result.scalars().all()


async def get_active_users_without_client(session: AsyncSession) -> list[BotUser]:
    now = datetime.now(timezone.utc)
    stmt = select(BotUser).where(
        and_(
            BotUser.vpn_subscription_end > now,
            BotUser.vpn_client_id.is_(None),
        )
    )
    result = await session.execute(stmt)
    return result.scalars().all()


# ---- ДОБАВЛЕННЫЕ ФУНКЦИИ ДЛЯ СОВМЕСТИМОСТИ ----

async def update_vpn_subscription(
    session: AsyncSession,
    telegram_id: int,
    days: int,
) -> bool:
    user = await get_user_by_telegram_id(session, telegram_id)
    if not user:
        logger.error(f"User {telegram_id} not found for VPN subscription update")
        return False

    now = datetime.now(timezone.utc)
    if user.vpn_subscription_end and user.vpn_subscription_end > now:
        new_end = user.vpn_subscription_end + timedelta(days=days)
    else:
        new_end = now + timedelta(days=days)

    user.vpn_subscription_end = new_end
    logger.info(f"VPN subscription updated for {telegram_id} until {new_end}")
    return True


async def update_bypass_subscription(
    session: AsyncSession,
    telegram_id: int,
    days: int,
) -> bool:
    user = await get_user_by_telegram_id(session, telegram_id)
    if not user:
        logger.error(f"User {telegram_id} not found for Bypass subscription update")
        return False

    now = datetime.now(timezone.utc)
    if user.bypass_subscription_end and user.bypass_subscription_end > now:
        new_end = user.bypass_subscription_end + timedelta(days=days)
    else:
        new_end = now + timedelta(days=days)

    user.bypass_subscription_end = new_end
    logger.info(f"Bypass subscription updated for {telegram_id} until {new_end}")
    return True


async def get_user_full_data(session: AsyncSession, telegram_id: int) -> Optional[dict]:
    user = await get_user_by_telegram_id(session, telegram_id)
    if not user:
        return None

    return {
        "id": user.id,
        "telegram_id": user.telegram_id,
        "username": user.username,
        "email": user.email,
        "vpn_subscription_end": user.vpn_subscription_end,
        "bypass_subscription_end": user.bypass_subscription_end,
        "vpn_client_id": user.vpn_client_id,
        "last_reminder_sent": user.last_reminder_sent,
        "created_at": user.created_at,
        "updated_at": user.updated_at,
    }