import logging
from typing import Optional
from db.crud import get_or_create_bot_user, set_vpn_client_id, set_vpn_server_id
from services.server_pool import ServerPool
from services.vpn_provider import XUIVPNProvider

logger = logging.getLogger(__name__)

class VPNManager:
    def __init__(self, server_pool: ServerPool):
        self.pool = server_pool

    async def create_key(self, user_id: int, days: int) -> Optional[str]:
        try:
            user = await get_or_create_bot_user(user_id)
            if not user:
                return None

            email = f"user_{user_id}@96vpn.bot"

            # Если у пользователя уже есть сервер и ключ – проверяем существование и возвращаем ссылку
            if user.vpn_client_id and user.server_id:
                provider = await self.pool.get_provider(user.server_id)
                if provider:
                    client = await provider.get_client_by_email(email)
                    if client and client.get("subId"):
                        link = provider.get_subscription_link(client["subId"])
                        logger.info(f"Existing key for user {user_id}: {link}")
                        return link

            # Выбираем сервер из пула
            server = await self.pool.get_server()
            if not server:
                logger.error("No active VPN servers available")
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
            logger.error(f"Error creating key for user {user_id}: {e}", exc_info=True)
            return None
    
    async def get_or_create_link(self, user_id: int) -> Optional[str]:
        user = await get_or_create_bot_user(user_id)
        if not user:
            return None

        email = f"user_{user_id}@96vpn.bot"

        # Если у пользователя уже есть клиент и известен сервер – пытаемся получить ссылку через провайдера
        if user.vpn_client_id and user.server_id:
            provider = await self.pool.get_provider(user.server_id)
            if provider:
                client_data = await provider.get_client_by_email(email)
                if client_data and client_data.get("subId"):
                    return provider.get_subscription_link(client_data["subId"])

        # Если нет – создаём новый ключ
        return await self.create_key(user_id, 30)   # days не важен, подписка уже активна

    async def revoke_key(self, user_id: int) -> bool:
        try:
            user = await get_or_create_bot_user(user_id)
            if not user or not user.vpn_client_id:
                logger.warning(f"User {user_id} has no active key")
                return True

            # Определяем сервер, на котором создан ключ
            server_id = user.server_id
            if not server_id:
                # fallback: пытаемся отозвать на всех? Или выбрасываем ошибку
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
            logger.error(f"Error revoking key for user {user_id}: {e}", exc_info=True)
            return False