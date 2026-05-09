"""CRUD операции для бота (BotUser), платежей (BotPayment), категорий и промптов."""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from db.base import AsyncSessionLocal
from db.models import BotUser, BotPayment, Category, Prompt

logger = logging.getLogger(__name__)


# ---------- BotUser ----------
async def _get_or_create_bot_user(
    session: AsyncSession,
    telegram_id: int,
    username: Optional[str],
    email: Optional[str]
) -> BotUser:
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
        await session.commit()
    return user

async def get_or_create_bot_user(
    telegram_id: int,
    username: Optional[str] = None,
    email: Optional[str] = None,
    session: Optional[AsyncSession] = None
) -> Optional[BotUser]:
    if session is None:
        async with AsyncSessionLocal() as new_session:
            return await _get_or_create_bot_user(new_session, telegram_id, username, email)
    else:
        return await _get_or_create_bot_user(session, telegram_id, username, email)


async def set_vpn_subscription(telegram_id: int, days: int) -> None:
    """Установить или продлить VPN-подписку."""
    async with AsyncSessionLocal() as session:
        user = await get_or_create_bot_user(telegram_id, session=session)
        now = datetime.now(timezone.utc)
        if user.vpn_subscription_end and user.vpn_subscription_end > now:
            user.vpn_subscription_end = user.vpn_subscription_end + timedelta(days=days)
        else:
            user.vpn_subscription_end = now + timedelta(days=days)
        user.updated_at = now
        await session.commit()
        logger.info(f"VPN subscription set for user {telegram_id} until {user.vpn_subscription_end}")


async def set_bypass_subscription(telegram_id: int, days: int) -> None:
    """Установить или продлить обход DPI."""
    async with AsyncSessionLocal() as session:
        user = await get_or_create_bot_user(telegram_id, session=session)
        now = datetime.now(timezone.utc)
        if user.bypass_subscription_end and user.bypass_subscription_end > now:
            user.bypass_subscription_end = user.bypass_subscription_end + timedelta(days=days)
        else:
            user.bypass_subscription_end = now + timedelta(days=days)
        user.updated_at = now
        await session.commit()
        logger.info(f"Bypass subscription set for user {telegram_id} until {user.bypass_subscription_end}")


async def set_vpn_client_id(telegram_id: int, client_uuid: Optional[str]) -> None:
    """Установить или очистить VPN client ID."""
    async with AsyncSessionLocal() as session:
        user = await get_or_create_bot_user(telegram_id, session=session)
        user.vpn_client_id = client_uuid
        user.updated_at = datetime.now(timezone.utc)
        await session.commit()


async def get_vpn_end(telegram_id: int) -> Optional[datetime]:
    """Возвращает дату окончания VPN-подписки."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(BotUser.vpn_subscription_end).where(BotUser.telegram_id == telegram_id))
        return result.scalar()


async def get_bypass_end(telegram_id: int) -> Optional[datetime]:
    """Возвращает дату окончания обхода DPI."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(BotUser.bypass_subscription_end).where(BotUser.telegram_id == telegram_id))
        return result.scalar()


async def is_vpn_active(telegram_id: int) -> bool:
    """Активна ли VPN-подписка."""
    end = await get_vpn_end(telegram_id)
    return end is not None and end > datetime.now(timezone.utc)


async def is_bypass_active(telegram_id: int) -> bool:
    """Активен ли обход DPI."""
    end = await get_bypass_end(telegram_id)
    return end is not None and end > datetime.now(timezone.utc)


async def get_vpn_client_id(telegram_id: int) -> Optional[str]:
    """Получить VPN client ID."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(BotUser.vpn_client_id).where(BotUser.telegram_id == telegram_id))
        return result.scalar()


# ---------- Bot Payments ----------
async def log_bot_payment(payment_id: str, telegram_id: int) -> bool:
    """Записывает платёж бота. Возвращает False, если payment_id уже существует."""
    async with AsyncSessionLocal() as session:
        existing = await session.execute(select(BotPayment).where(BotPayment.payment_id == payment_id))
        if existing.scalars().first():
            return False
        session.add(BotPayment(payment_id=payment_id, telegram_id=telegram_id))
        await session.commit()
        return True


async def is_bot_payment_processed(payment_id: str) -> bool:
    """Проверяет, был ли уже обработан платёж."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(BotPayment).where(BotPayment.payment_id == payment_id))
        return result.scalars().first() is not None


# ---------- Категории ----------
async def add_category(name: str) -> Optional[Category]:
    async with AsyncSessionLocal() as session:
        existing = await session.execute(select(Category).where(Category.name == name))
        if existing.scalars().first():
            return None
        cat = Category(name=name)
        session.add(cat)
        await session.commit()
        await session.refresh(cat)
        return cat


async def get_all_categories() -> list[str]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Category.name).order_by(Category.name))
        return [row[0] for row in result.all()]


async def rename_category(old_name: str, new_name: str) -> bool:
    async with AsyncSessionLocal() as session:
        cat = await session.execute(select(Category).where(Category.name == old_name))
        cat = cat.scalars().first()
        if not cat:
            return False
        cat.name = new_name
        await session.commit()
        return True


async def delete_category(name: str) -> bool:
    async with AsyncSessionLocal() as session:
        cat = await session.execute(select(Category).where(Category.name == name))
        cat = cat.scalars().first()
        if not cat:
            return False
        await session.execute(delete(Prompt).where(Prompt.category_id == cat.id))
        await session.delete(cat)
        await session.commit()
        return True


# ---------- Промпты ----------
async def add_prompt(title: str, description: str, content: str, category_name: str, is_free: bool = False) -> Optional[Prompt]:
    async with AsyncSessionLocal() as session:
        cat = await session.execute(select(Category).where(Category.name == category_name))
        cat = cat.scalars().first()
        if not cat:
            return None
        prompt = Prompt(
            title=title,
            description=description,
            content=content,
            category_id=cat.id,
            is_free=is_free
        )
        session.add(prompt)
        await session.commit()
        await session.refresh(prompt)
        return prompt


async def get_prompts_by_category(category_name: Optional[str] = None) -> list[dict]:
    async with AsyncSessionLocal() as session:
        if category_name:
            cat = await session.execute(select(Category).where(Category.name == category_name))
            cat = cat.scalars().first()
            if not cat:
                return []
            stmt = (select(Prompt)
                    .where(Prompt.category_id == cat.id)
                    .options(selectinload(Prompt.category))
                    .order_by(Prompt.title))
        else:
            stmt = (select(Prompt)
                    .options(selectinload(Prompt.category))
                    .order_by(Prompt.title))
        result = await session.execute(stmt)
        prompts = result.scalars().all()
        return [
            {
                "id": p.id,
                "title": p.title,
                "description": p.description,
                "content": p.content,
                "category": p.category.name,
                "is_free": p.is_free,
                "usage_count": p.usage_count,
                "rating": p.rating,
                "created_at": p.created_at.isoformat() if p.created_at else None
            }
            for p in prompts
        ]


async def get_prompts_data() -> dict:
    """Возвращает словарь с ключами 'prompts' и 'categories'."""
    async with AsyncSessionLocal() as session:
        stmt = select(Prompt).options(selectinload(Prompt.category)).order_by(Prompt.title)
        result = await session.execute(stmt)
        prompts = result.scalars().all()

        result_cat = await session.execute(select(Category.name).order_by(Category.name))
        categories = [row[0] for row in result_cat.all()]

        return {
            "prompts": [
                {
                    "id": p.id,
                    "title": p.title,
                    "description": p.description,
                    "content": p.content,
                    "category": p.category.name,
                    "is_free": p.is_free,
                    "usage_count": p.usage_count,
                    "rating": p.rating,
                    "created_at": p.created_at.isoformat() if p.created_at else None
                }
                for p in prompts
            ],
            "categories": categories
        }


async def get_prompt_by_id(prompt_id: int) -> Optional[dict]:
    async with AsyncSessionLocal() as session:
        p = await session.execute(
            select(Prompt)
            .where(Prompt.id == prompt_id)
            .options(selectinload(Prompt.category))
        )
        p = p.scalars().first()
        if not p:
            return None
        return {
            "id": p.id,
            "title": p.title,
            "description": p.description,
            "content": p.content,
            "category": p.category.name,
            "is_free": p.is_free,
            "usage_count": p.usage_count,
            "rating": p.rating
        }


async def update_prompt(prompt_id: int, **kwargs) -> bool:
    async with AsyncSessionLocal() as session:
        p = await session.execute(select(Prompt).where(Prompt.id == prompt_id))
        p = p.scalars().first()
        if not p:
            return False
        for key, value in kwargs.items():
            if key == "category_name":
                cat = await session.execute(select(Category).where(Category.name == value))
                cat = cat.scalars().first()
                if cat:
                    p.category_id = cat.id
            elif hasattr(p, key):
                setattr(p, key, value)
        await session.commit()
        return True


async def delete_prompt(prompt_id: int) -> bool:
    async with AsyncSessionLocal() as session:
        p = await session.execute(select(Prompt).where(Prompt.id == prompt_id))
        p = p.scalars().first()
        if not p:
            return False
        await session.delete(p)
        await session.commit()
        return True