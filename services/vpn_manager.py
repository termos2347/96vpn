import logging
from typing import Optional
from services.vpn_provider import vpn_provider
from db.crud import set_vpn_client_id, get_or_create_user

logger = logging.getLogger(__name__)

class VPNManager:
    def __init__(self):
        self.provider = vpn_provider

    async def create_key(self, user_id: int, days: int) -> Optional[str]:
        try:
            user = await get_or_create_user(user_id)
            if not user:
                logger.error(f"Не удалось получить пользователя {user_id}")
                return None

            email = f"user_{user_id}@96vpn.bot"

            if user.vpn_client_id:
                existing = await self.provider.get_client_by_email(email)
                if existing and existing.get("subId"):
                    sub_link = self.provider.get_subscription_link(existing["subId"])
                    logger.info(f"Найден существующий ключ для user_id={user_id}: {sub_link}")
                    return sub_link

            client_data = await self.provider.create_client(email)
            if not client_data:
                logger.error(f"Не удалось создать клиента для user_id={user_id}")
                return None

            client_uuid = client_data['uuid']
            sub_id = client_data['subId']

            await set_vpn_client_id(user_id, client_uuid)
            sub_link = self.provider.get_subscription_link(sub_id)
            logger.info(f"Ключ создан для user_id={user_id}, sub_link: {sub_link}")
            return sub_link

        except Exception as e:
            logger.error(f"Ошибка при создании ключа для user_id={user_id}: {e}", exc_info=True)
            return None

    async def revoke_key(self, user_id: int) -> bool:
        try:
            user = await get_or_create_user(user_id)
            if not user or not user.vpn_client_id:
                logger.warning(f"Пользователь {user_id} не имеет активного ключа")
                return True

            success = await self.provider.revoke_client(user.vpn_client_id)
            if success:
                await set_vpn_client_id(user_id, None)
                logger.info(f"Ключ отозван для user_id={user_id}")
            else:
                logger.error(f"Не удалось отозвать ключ для user_id={user_id}")
            return success

        except Exception as e:
            logger.error(f"Ошибка при отзыве ключа для user_id={user_id}: {e}", exc_info=True)
            return False

    async def get_subscription_link(self, user_id: int) -> Optional[str]:
        try:
            user = await get_or_create_user(user_id)
            if not user or not user.vpn_client_id:
                return None
            email = f"user_{user_id}"
            client_data = await self.provider.get_client_by_email(email)
            if client_data:
                sub_link = self.provider.get_subscription_link(client_data['subId'])
                return sub_link
            return None
        except Exception as e:
            logger.error(f"Ошибка при получении ссылки подписки для user_id={user_id}: {e}", exc_info=True)
            return None

    async def close(self):
        await self.provider.close()