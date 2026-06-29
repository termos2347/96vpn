import asyncio
from datetime import datetime, timedelta, timezone
import logging
from typing import Optional, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from db.base import AsyncSessionLocal, retry_db_operation
from db.crud import get_or_create_bot_user
from services.server_pool import ServerPool
import aiohttp

logger = logging.getLogger(__name__)

class VPNManager:
    _user_locks: Dict[int, asyncio.Lock] = {}
    _lock_cleanup_lock = asyncio.Lock()

    def __init__(self, server_pool: ServerPool):
        self.pool = server_pool

    async def _get_user_lock(self, user_id: int) -> asyncio.Lock:
        async with self._lock_cleanup_lock:
            if user_id not in self._user_locks:
                self._user_locks[user_id] = asyncio.Lock()
            return self._user_locks[user_id]

    @retry_db_operation(max_retries=3)
    async def create_key(self, user_id: int, days: int) -> Optional[str]:
        lock = await self._get_user_lock(user_id)
        async with lock:
            async with AsyncSessionLocal() as session:
                async with session.begin():
                    return await self._create_key_unsafe(user_id, days, session)

    async def _create_key_unsafe(
        self,
        user_id: int,
        days: int,
        session: AsyncSession
    ) -> Optional[str]:
        max_retries = 3
        for attempt in range(max_retries):
            try:
                user = await get_or_create_bot_user(session, user_id)
                email = f"user_{user_id}@96vpn.bot"

                if user.vpn_client_id and user.server_id:
                    provider = await self.pool.get_provider(user.server_id)
                    if provider:
                        client = await provider.get_client_by_email(email)
                        if client and client.get("subId"):
                            link = provider.get_subscription_link(client["subId"])
                            logger.info(f"Existing key for user {user_id}: {link}")
                            # Синхронизация: обновляем vpn_client_id на случай, если он изменился
                            user.vpn_client_id = client["uuid"]
                            # server_id оставляем прежним (он уже верный)
                            await session.commit()
                            return link
                        else:
                            logger.warning(f"Stale client_id {user.vpn_client_id} for user {user_id}, will recreate")
                            user.vpn_client_id = None
                            user.server_id = None

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

                user.vpn_client_id = client_uuid
                user.server_id = server.id

                link = provider.get_subscription_link(sub_id)
                logger.info(f"Key created for user {user_id} on server {server.id}: {link}")
                return link

            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                logger.warning(f"Network error on attempt {attempt+1}/{max_retries} for user {user_id}: {e}")
                if attempt == max_retries - 1:
                    logger.error(f"All retries failed for user {user_id}")
                    return None
                await asyncio.sleep(2 ** attempt)
            except Exception as e:
                logger.exception(f"Unexpected error creating key for user {user_id}")
                return None
        return None

    @retry_db_operation(max_retries=3)
    async def get_or_create_link(self, user_id: int) -> Optional[str]:
        lock = await self._get_user_lock(user_id)
        async with lock:
            async with AsyncSessionLocal() as session:
                async with session.begin():
                    user = await get_or_create_bot_user(session, user_id)
                    now = datetime.now(timezone.utc)
                    if user.vpn_subscription_end is None or user.vpn_subscription_end <= now:
                        logger.info(f"User {user_id} has no active subscription (end={user.vpn_subscription_end})")
                        return None
                    return await self._create_key_unsafe(user_id, 30, session)

    @retry_db_operation(max_retries=3)
    async def revoke_key(self, user_id: int) -> bool:
        lock = await self._get_user_lock(user_id)
        async with lock:
            async with AsyncSessionLocal() as session:
                async with session.begin():
                    return await self._revoke_key_unsafe(user_id, session)

    async def _revoke_key_unsafe(self, user_id: int, session: AsyncSession) -> bool:
        """Возвращает True, если ключ успешно отозван (или уже отсутствует)."""
        try:
            user = await get_or_create_bot_user(session, user_id)
            if not user.vpn_client_id:
                logger.info(f"User {user_id} has no active key to revoke")
                return True

            server_id = user.server_id
            client_id = user.vpn_client_id

            if not server_id:
                logger.error(f"No server_id for user {user_id}, cannot revoke on panel. Client {client_id} remains on panel.")
                return False

            provider = await self.pool.get_provider(server_id)
            if not provider:
                logger.error(f"Provider for server {server_id} not found. Client {client_id} remains on panel.")
                return False

            max_retries = 3
            for attempt in range(max_retries):
                try:
                    success = await provider.revoke_client(client_id)
                    if success:
                        logger.info(f"Key revoked on panel for user {user_id} on server {server_id} (attempt {attempt+1})")
                        user.vpn_client_id = None
                        user.server_id = None
                        user.vpn_subscription_end = datetime.now(timezone.utc) - timedelta(days=1)
                        return True
                    else:
                        client_info = await provider.get_client_by_uuid(client_id)
                        if client_info is None:
                            logger.info(f"Client {client_id} not found on panel, assuming already revoked. Updating DB.")
                            user.vpn_client_id = None
                            user.server_id = None
                            user.vpn_subscription_end = datetime.now(timezone.utc) - timedelta(days=1)
                            return True
                        else:
                            logger.warning(f"revoke_client returned False but client exists, attempt {attempt+1}")
                except Exception as e:
                    logger.exception(f"Error revoking client on panel for user {user_id}, attempt {attempt+1}: {e}")
                    if attempt == max_retries - 1:
                        return False
                    await asyncio.sleep(2 ** attempt)

            logger.error(f"All retries failed to revoke client {client_id} for user {user_id}")
            return False

        except Exception as e:
            logger.exception(f"Unexpected error in _revoke_key_unsafe for user {user_id}")
            return False