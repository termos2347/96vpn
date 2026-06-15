import asyncio
import logging
from typing import Optional, Dict
from db.crud import get_or_create_bot_user, set_vpn_client_id, set_vpn_server_id
from services.server_pool import ServerPool

logger = logging.getLogger(__name__)

class VPNManager:
    # Словарь блокировок для каждого пользователя
    _user_locks: Dict[int, asyncio.Lock] = {}
    _lock_cleanup_lock = asyncio.Lock()

    def __init__(self, server_pool: ServerPool):
        self.pool = server_pool

    async def _get_user_lock(self, user_id: int) -> asyncio.Lock:
        """Возвращает блокировку для пользователя (создаёт, если нет)."""
        async with self._lock_cleanup_lock:
            if user_id not in self._user_locks:
                self._user_locks[user_id] = asyncio.Lock()
            return self._user_locks[user_id]

    async def _release_user_lock(self, user_id: int):
        """Опционально: удаляет блокировку из словаря, если она не используется.
           Вызывать после отпускания блокировки, если хотим экономить память."""
        async with self._lock_cleanup_lock:
            lock = self._user_locks.get(user_id)
            if lock and not lock._waiters:   # нет ожидающих
                self._user_locks.pop(user_id, None)

    async def create_key(self, user_id: int, days: int) -> Optional[str]:
        """Создаёт ключ с блокировкой для user_id."""
        lock = await self._get_user_lock(user_id)
        async with lock:
            return await self._create_key_unsafe(user_id, days)

    async def _create_key_unsafe(self, user_id: int, days: int) -> Optional[str]:
        """Внутренний метод без блокировки (вызывается уже под блокировкой)."""
        try:
            user = await get_or_create_bot_user(user_id)
            if not user:
                return None

            email = f"user_{user_id}@96vpn.bot"

            # Если у пользователя уже есть сервер и ключ – проверяем существование
            if user.vpn_client_id and user.server_id:
                provider = await self.pool.get_provider(user.server_id)
                if provider:
                    client = await provider.get_client_by_email(email)
                    if client and client.get("subId"):
                        link = provider.get_subscription_link(client["subId"])
                        logger.info(f"Existing key for user {user_id}: {link}")
                        return link
                    else:
                        logger.warning(f"Stale client_id {user.vpn_client_id} for user {user_id}, will recreate")
                        await set_vpn_client_id(user_id, None)
                        await set_vpn_server_id(user_id, None)

            # Выбираем сервер из пула
            server = await self.pool.get_server()
            if not server:
                logger.error("No active servers available")
                return None

            provider = await self.pool.get_provider(server.id)
            if not provider:
                logger.error(f"Provider for server {server.id} not found")
                return None

            client_data = await provider.create_client(email)
            if not client_data:
                logger.error(f"Failed to create client on server {server.id} for user {user_id}")
                return None

            client_uuid = client_data['uuid']
            sub_id = client_data['subId']

            # Сохраняем server_id и client_id
            await set_vpn_client_id(user_id, client_uuid)
            await set_vpn_server_id(user_id, server.id)

            link = provider.get_subscription_link(sub_id)
            logger.info(f"Key created for user {user_id} on server {server.id}: {link}")
            return link

        except Exception as e:
            logger.error(f"Error creating key for user {user_id}", exc_info=True)
            return None
        finally:
            # Опционально: удаляем блокировку, если нет ожидающих (можно закомментировать)
            await self._release_user_lock(user_id)

    async def get_or_create_link(self, user_id: int) -> Optional[str]:
        """Получить существующую ссылку или создать новую (для активной подписки)."""
        return await self.create_key(user_id, 30)

    async def revoke_key(self, user_id: int) -> bool:
        """Отзыв ключа – тоже стоит защитить блокировкой, чтобы не пересекалось с созданием."""
        lock = await self._get_user_lock(user_id)
        async with lock:
            return await self._revoke_key_unsafe(user_id)

    async def _revoke_key_unsafe(self, user_id: int) -> bool:
        """Внутренний метод для отзыва без блокировки."""
        try:
            user = await get_or_create_bot_user(user_id)
            if not user or not user.vpn_client_id:
                logger.info(f"User {user_id} has no active key to revoke")
                return True

            server_id = user.server_id
            if not server_id:
                logger.error(f"No server_id for user {user_id}, cannot revoke")
                return False

            provider = await self.pool.get_provider(server_id)
            if not provider:
                logger.error(f"Provider for server {server_id} not found")
                return False

            success = await provider.revoke_client(user.vpn_client_id)
            if success:
                await set_vpn_client_id(user_id, None)
                await set_vpn_server_id(user_id, None)
                logger.info(f"Key revoked for user {user_id} on server {server_id}")
            else:
                logger.error(f"Failed to revoke key for user {user_id} on server {server_id}")
            return success

        except Exception as e:
            logger.error(f"Error revoking key for user {user_id}", exc_info=True)
            return False
        finally:
            await self._release_user_lock(user_id)