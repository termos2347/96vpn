import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from db.base import AsyncSessionLocal, retry_db_operation
from db.crud import get_or_create_bot_user
from services.vpn_provider import XUIVPNProvider

logger = logging.getLogger(__name__)


class VPNManager:
    def __init__(self, provider: XUIVPNProvider):
        self.provider = provider
        # Для блокировок пользователей (чтобы не создавать два ключа одновременно)
        self._user_locks = {}

    def _get_user_lock(self, user_id: int) -> asyncio.Lock:
        if user_id not in self._user_locks:
            self._user_locks[user_id] = asyncio.Lock()
        return self._user_locks[user_id]

    @retry_db_operation(max_retries=3)
    async def create_key(self, user_id: int, days: int) -> Optional[str]:
        """
        Создаёт или обновляет ключ для пользователя на единственной панели.
        Если у пользователя уже есть активный клиент, возвращает его ссылку.
        Иначе создаёт нового клиента.
        """
        lock = self._get_user_lock(user_id)
        async with lock:
            async with AsyncSessionLocal() as session:
                async with session.begin():
                    return await self._create_key_unsafe(user_id, days, session)

    async def _create_key_unsafe(self, user_id: int, days: int, session: AsyncSession) -> Optional[str]:
        user = await get_or_create_bot_user(session, user_id)
        email = f"user_{user_id}@96vpn.bot"

        # Если у пользователя уже есть client_id, пробуем получить ссылку
        if user.vpn_client_id:
            # Проверяем, существует ли клиент на панели
            client = await self.provider.get_client_by_uuid(user.vpn_client_id)
            if client and client.get("subId"):
                link = self.provider.get_subscription_link(client["subId"])
                logger.info(f"Existing key for user {user_id}: {link}")
                return link
            else:
                logger.warning(f"Stored client_id {user.vpn_client_id} not found on panel, will recreate")
                user.vpn_client_id = None  # очистим, чтобы создать нового

        # Создаём нового клиента с таймаутом
        try:
            client_data = await asyncio.wait_for(
                self.provider.create_client(email),
                timeout=15.0
            )
        except asyncio.TimeoutError:
            logger.error(f"Timeout creating client for user {user_id}")
            # Уведомление админа будет выше
            return None
        except Exception as e:
            logger.exception(f"Error creating client for user {user_id}: {e}")
            return None

        if not client_data:
            logger.error(f"Failed to create client for user {user_id}")
            return None

        client_uuid = client_data['uuid']
        sub_id = client_data['subId']

        user.vpn_client_id = client_uuid
        # server_id больше не храним
        # user.server_id = None  # если поле осталось, можно занулить

        link = self.provider.get_subscription_link(sub_id)
        logger.info(f"Key created for user {user_id}: {link}")
        return link

    @retry_db_operation(max_retries=3)
    async def get_or_create_link(self, user_id: int) -> Optional[str]:
        """Аналог create_key, но без указания дней (используется для получения ссылки после оплаты)."""
        lock = self._get_user_lock(user_id)
        async with lock:
            async with AsyncSessionLocal() as session:
                async with session.begin():
                    user = await get_or_create_bot_user(session, user_id)
                    now = datetime.now(timezone.utc)
                    if user.vpn_subscription_end is None or user.vpn_subscription_end <= now:
                        logger.info(f"User {user_id} has no active subscription")
                        return None
                    # Дни берём из разницы, но можно передать произвольные, так как мы не продлеваем здесь
                    # Для простоты возьмём 30 дней (но это не влияет на создание клиента, т.к. expiryTime=0)
                    return await self._create_key_unsafe(user_id, 30, session)

    @retry_db_operation(max_retries=3)
    async def revoke_key(self, user_id: int) -> bool:
        lock = self._get_user_lock(user_id)
        async with lock:
            async with AsyncSessionLocal() as session:
                async with session.begin():
                    return await self._revoke_key_unsafe(user_id, session)

    async def _revoke_key_unsafe(self, user_id: int, session: AsyncSession) -> bool:
        user = await get_or_create_bot_user(session, user_id)
        if not user.vpn_client_id:
            logger.info(f"User {user_id} has no active key to revoke")
            return True

        client_uuid = user.vpn_client_id
        # Пытаемся отозвать клиент на панели
        try:
            success = await asyncio.wait_for(
                self.provider.revoke_client(client_uuid),
                timeout=15.0
            )
            if success:
                logger.info(f"Key revoked on panel for user {user_id}")
            else:
                # Проверяем, существует ли клиент
                client = await self.provider.get_client_by_uuid(client_uuid)
                if client is None:
                    logger.info(f"Client {client_uuid} not found on panel, assuming already revoked")
                else:
                    logger.error(f"Failed to revoke client {client_uuid} for user {user_id}")
                    return False
        except asyncio.TimeoutError:
            logger.error(f"Timeout revoking client {client_uuid} for user {user_id}")
            return False
        except Exception as e:
            logger.exception(f"Error revoking client {client_uuid} for user {user_id}: {e}")
            return False

        # Обновляем БД
        user.vpn_client_id = None
        user.vpn_subscription_end = datetime.now(timezone.utc) - timedelta(days=1)
        return True