import logging
from sqlalchemy import select, update, delete
from sqlalchemy.exc import IntegrityError
from .base import AsyncSessionLocal
from .models import Client, User
from datetime import datetime

logger = logging.getLogger(__name__)

async def create_client(email: str, username: str) -> Client:
    async with AsyncSessionLocal() as session:
        try:
            client = Client(email=email, username=username, created_at=datetime.utcnow())
            logger.info(f"Creating client with email: {email}, username: {username}")
            session.add(client)
            await session.commit()
            await session.refresh(client)
            return client
        except IntegrityError as e:
            await session.rollback()
            logger.error(f"Error creating client: {e}")
            raise

async def get_client(client_id: int) -> Client | None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Client).where(Client.client_id == client_id))
        return result.scalar_one_or_none()

async def update_client(client_id: int, email: str, username: str) -> bool:
    async with AsyncSessionLocal() as session:
        try:
            stmt = update(Client).where(Client.client_id == client_id).values(email=email, username=username)
            await session.execute(stmt)
            await session.commit()
            return True
        except Exception as e:
            logger.error(f"Error updating client with id {client_id}: {e}")
            return False

async def get_or_create_user(user_id: int, username: str = None) -> User:
    """Получить или создать пользователя по user_id."""
    async with AsyncSessionLocal() as session:
        user = await session.execute(select(User).where(User.user_id == user_id))
        user = user.scalar_one_or_none()
        if not user:
            user = User(user_id=user_id, username=username)
            session.add(user)
            await session.commit()
            await session.refresh(user)
        return user

async def set_vpn_client_id(user_id: int, client_id: str) -> bool:
    """Установить идентификатор VPN-клиента для пользователя."""
    async with AsyncSessionLocal() as session:
        user = await session.execute(select(User).where(User.user_id == user_id))
        user = user.scalar_one_or_none()
        if user:
            user.vpn_client_id = client_id
            await session.commit()
            return True
    return False

async def delete_client(client_id: int) -> bool:
    async with AsyncSessionLocal() as session:
        try:
            stmt = delete(Client).where(Client.client_id == client_id)
            await session.execute(stmt)
            await session.commit()
            return True
        except Exception as e:
            logger.error(f"Error deleting client with id {client_id}: {e}")
            return False