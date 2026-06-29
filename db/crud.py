import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.base import AsyncSessionLocal
from db.models import BotUser, BotPayment
from config import settings

logger = logging.getLogger(__name__)

# ---------- BotUser ----------
async def get_or_create_bot_user(
    session: AsyncSession,
    telegram_id: int,
    username: Optional[str] = None
) -> BotUser:
    """
    Получить пользователя по telegram_id, при необходимости создать.
    Если передан username, обновить поле (если изменилось).
    """
    stmt = select(BotUser).where(BotUser.telegram_id == telegram_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        user = BotUser(telegram_id=telegram_id, username=username)
        session.add(user)
        await session.flush()
        logger.info(f"Created new user {telegram_id} with username {username}")
    else:
        # Обновляем username, если он изменился
        if username and user.username != username:
            user.username = username
            session.add(user)
            logger.debug(f"Updated username for user {telegram_id} to {username}")

    return user

async def update_vpn_subscription(
    session: AsyncSession,
    telegram_id: int,
    days: int,
    create_if_missing: bool = True
) -> Optional[BotUser]:
    """Обновляет VPN-подписку. Если пользователь не найден и create_if_missing=False – возвращает None."""
    if create_if_missing:
        user = await get_or_create_bot_user(session, telegram_id)
    else:
        user = await get_user_by_telegram_id(session, telegram_id)
        if not user:
            return None
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

async def get_user_by_telegram_id(
    session: AsyncSession,
    telegram_id: int
) -> Optional[BotUser]:
    """Возвращает пользователя или None, если не найден."""
    result = await session.execute(
        select(BotUser).where(BotUser.telegram_id == telegram_id)
    )
    return result.scalars().first()

async def get_user_full_data(telegram_id: int) -> Optional[dict]:
    """
    Возвращает полную информацию о пользователе.
    Если пользователь не найден – возвращает None.
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(
                BotUser.telegram_id,
                BotUser.username,
                BotUser.email,
                BotUser.vpn_subscription_end,
                BotUser.bypass_subscription_end,
                BotUser.vpn_client_id,
                BotUser.server_id,
                BotUser.created_at,
                BotUser.updated_at
            ).where(BotUser.telegram_id == telegram_id)
        )
        row = result.first()
        if row:
            return {
                "telegram_id": row[0],
                "username": row[1],
                "email": row[2],
                "vpn_subscription_end": row[3],
                "bypass_subscription_end": row[4],
                "vpn_client_id": row[5],
                "server_id": row[6],
                "created_at": row[7],
                "updated_at": row[8]
            }
        return None

# ---------- Атомарная активация с валидацией ----------
async def activate_subscription(
    session: AsyncSession,
    telegram_id: int,
    product_type: str,
    period: str,
    payment_id: Optional[str] = None,
    user: Optional[BotUser] = None
) -> bool:
    """
    Активирует подписку пользователя.
    Возвращает True, если активация выполнена (подписка была неактивна или отсутствовала).
    Возвращает False, если подписка уже активна на момент вызова.
    При невалидных параметрах выбрасывает ValueError.
    Если передан user, он уже должен быть заблокирован (FOR UPDATE) и находиться в сессии.
    """
    # ---- Валидация ----
    if not isinstance(telegram_id, int) or telegram_id <= 0:
        raise ValueError("telegram_id must be a positive integer")
    if product_type not in ("vpn", "bypass"):
        raise ValueError("product_type must be 'vpn' or 'bypass'")
    if period not in settings.PERIOD_DAYS:
        raise ValueError(f"invalid period, allowed: {list(settings.PERIOD_DAYS.keys())}")
    if product_type == "bypass" and period not in ("1m", "3m"):
        raise ValueError("bypass supports only 1m and 3m periods")

    # ---- Получение пользователя (если не передан) ----
    if user is None:
        stmt = select(BotUser).where(BotUser.telegram_id == telegram_id).with_for_update()
        user = (await session.execute(stmt)).scalar_one_or_none()
        if not user:
            user = BotUser(telegram_id=telegram_id)
            session.add(user)
            await session.flush()

    now = datetime.now(timezone.utc)

    # ---- Проверка, активна ли уже подписка ----
    if product_type == "vpn":
        if user.vpn_subscription_end and user.vpn_subscription_end > now:
            logger.info(f"User {telegram_id} already has active VPN subscription until {user.vpn_subscription_end}")
            return False
    else:  # bypass
        if user.bypass_subscription_end and user.bypass_subscription_end > now:
            logger.info(f"User {telegram_id} already has active bypass subscription until {user.bypass_subscription_end}")
            return False

    # ---- Расчёт новой даты окончания ----
    days = settings.PERIOD_DAYS[period]
    new_end = now + timedelta(days=days)

    # ---- Обновление подписки ----
    if product_type == "vpn":
        user.vpn_subscription_end = new_end
    else:
        user.bypass_subscription_end = new_end
    user.updated_at = now
    session.add(user)

    # ---- Обновление статуса платежа, если передан payment_id ----
    if payment_id:
        stmt = select(BotPayment).where(BotPayment.payment_id == payment_id)
        payment = (await session.execute(stmt)).scalar_one_or_none()
        if payment:
            payment.is_paid = True
            payment.status = "succeeded"
            payment.updated_at = now
            session.add(payment)
        else:
            logger.warning(f"Payment {payment_id} not found, but subscription activated")

    await session.flush()
    logger.info(f"Activated {product_type} subscription for user {telegram_id} until {new_end}")
    return True

# ---------- Вспомогательные функции для проверки ----------
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