import logging
from typing import Optional
from services.vpn_provider import XUIVPNProvider
from db.crud import set_vpn_client_id, get_or_create_user
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class VPNManager:
    def __init__(self):
        self.provider = XUIVPNProvider()

    async def create_key(self, user_id: int, days: int) -> Optional[str]:
        """Создает VPN-ключ для пользователя на указанное количество дней."""
        try:
            # Получаем или создаем пользователя
            user = await get_or_create_user(user_id)
            if not user:
                logger.error(f"Не удалось получить пользователя {user_id}")
                return None

            # Создаем клиента в XUI
            email = f"user_{user_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            client_data = await self.provider.create_client(email)
            if not client_data:
                logger.error(f"Не удалось создать клиента для user_id={user_id}")
                return None

            client_uuid = client_data['uuid']
            sub_id = client_data['subId']

            # Сохраняем client_id в БД
            await set_vpn_client_id(user_id, client_uuid)

            # Возвращаем ссылку подписки
            sub_link = self.provider.get_subscription_link(sub_id)
            logger.info(f"Ключ создан для user_id={user_id}, sub_link: {sub_link}")
            return sub_link

        except Exception as e:
            logger.error(f"Ошибка при создании ключа для user_id={user_id}: {e}", exc_info=True)
            return None

    async def revoke_key(self, user_id: int) -> bool:
        """Отзывает VPN-ключ пользователя."""
        try:
            user = await get_or_create_user(user_id)
            if not user or not user.vpn_client_id:
                logger.warning(f"Пользователь {user_id} не имеет активного ключа")
                return True  # Нечего отзывать

            success = await self.provider.revoke_client(user.vpn_client_id)
            if success:
                # Очищаем client_id в БД
                await set_vpn_client_id(user_id, None)
                logger.info(f"Ключ отозван для user_id={user_id}")
            else:
                logger.error(f"Не удалось отозвать ключ для user_id={user_id}")
            return success

        except Exception as e:
            logger.error(f"Ошибка при отзыве ключа для user_id={user_id}: {e}", exc_info=True)
            return False

    async def get_subscription_link(self, user_id: int) -> Optional[str]:
        """Возвращает ссылку подписки для пользователя."""
        try:
            user = await get_or_create_user(user_id)
            if not user or not user.vpn_client_id:
                return None

            # Ищем клиента по email (user_id)
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
        """Закрывает соединения провайдера."""
        await self.provider.close()