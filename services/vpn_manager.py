# services/vpn_manager.py
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
import uuid

from db.base import AsyncSessionLocal, retry_db_operation
from db.crud import get_or_create_bot_user
from services.vpn_provider import XUIVPNProvider

logger = logging.getLogger(__name__)

# Максимальный срок подписки – 96 лет (предотвращает переполнение)
MAX_SUBSCRIPTION_DAYS = 96 * 365


class VPNManager:
    def __init__(self, provider: XUIVPNProvider):
        self.provider = provider

    @retry_db_operation(max_retries=3)
    async def create_key(self, user_id: int, days: int, session=None) -> Optional[str]:
        """
        Создаёт клиента на панели 3x‑UI и обновляет запись в БД.
        Если передана сессия – использует её, иначе создаёт новую.
        """
        # Ограничиваем количество дней
        if days > MAX_SUBSCRIPTION_DAYS:
            logger.warning(f"Requested {days} days for user {user_id}, capped to {MAX_SUBSCRIPTION_DAYS}")
            days = MAX_SUBSCRIPTION_DAYS

        client_uuid = str(uuid.uuid4())
        email = f"tg_{user_id}_{client_uuid[:8]}"
        sub_id = client_uuid[:16]
        logger.info(f"Creating key: user={user_id}, email={email}, sub_id={sub_id}")

        # Создание клиента на панели
        try:
            client_data = await asyncio.wait_for(
                self.provider.create_client(email, sub_id),
                timeout=15.0
            )
        except asyncio.TimeoutError:
            logger.error(f"Timeout creating client for user {user_id}")
            await self._notify_admin_and_user(user_id, "таймаут при создании клиента на панели")
            return None
        except Exception as e:
            logger.exception(f"Error creating client for user {user_id}: {e}")
            await self._notify_admin_and_user(user_id, f"ошибка при создании клиента: {e}")
            return None

        if not client_data:
            logger.error(f"Failed to create client for user {user_id}")
            await self._notify_admin_and_user(user_id, "не удалось создать клиента на панели")
            return None

        sub_id = client_data.get('subId', sub_id)
        link = self.provider.get_subscription_link(sub_id)

        # Обновляем пользователя
        if session is None:
            async with AsyncSessionLocal() as sess:
                async with sess.begin():
                    user = await get_or_create_bot_user(sess, user_id)
                    self._update_user_object(user, client_uuid, link, days)
        else:
            user = await get_or_create_bot_user(session, user_id)
            self._update_user_object(user, client_uuid, link, days)

        return link

    def _update_user_object(self, user, client_uuid: str, link: str, days: int):
        """Обновляет объект пользователя (изменяет поля, не сохраняет)."""
        user.vpn_client_id = client_uuid
        now = datetime.now(timezone.utc)
        if user.vpn_subscription_end is None or user.vpn_subscription_end <= now:
            new_end = now + timedelta(days=days)
        else:
            new_end = user.vpn_subscription_end + timedelta(days=days)
        max_allowed = now + timedelta(days=MAX_SUBSCRIPTION_DAYS)
        if new_end > max_allowed:
            new_end = max_allowed
            logger.warning(f"Capped subscription end for user {user.telegram_id} to {max_allowed}")
        user.vpn_subscription_end = new_end
        logger.info(f"Updated user {user.telegram_id}: client_id={client_uuid}, end={new_end}")

    @retry_db_operation(max_retries=3)
    async def get_or_create_link(self, user_id: int) -> Optional[str]:
        """
        Получает существующую ссылку или создаёт новую, если ключа нет.
        Использует одну сессию на всю операцию.
        """
        logger.info(f"get_or_create_link called for user {user_id}")
        async with AsyncSessionLocal() as session:
            async with session.begin():
                user = await get_or_create_bot_user(session, user_id)
                now = datetime.now(timezone.utc)

                # Если подписка не активна – выходим
                if user.vpn_subscription_end is None or user.vpn_subscription_end <= now:
                    logger.info(f"User {user_id} has no active subscription")
                    return None

                email = None
                if user.vpn_client_id:
                    email = f"tg_{user_id}_{user.vpn_client_id[:8]}"

                client = None

                # 1. Поиск по полному email
                if email:
                    try:
                        logger.debug(f"Checking client by email: {email}")
                        client = await asyncio.wait_for(
                            self.provider.get_client_by_email(email),
                            timeout=10.0
                        )
                        if client:
                            logger.debug(f"Client found by email: {client}")
                    except asyncio.TimeoutError:
                        logger.warning(f"Timeout getting client by email for user {user_id}")
                    except Exception as e:
                        logger.exception(f"Error getting client by email for user {user_id}: {e}")

                # 2. Если не найден по email, ищем по subId
                if not client and user.vpn_client_id:
                    try:
                        logger.debug(f"Trying to find client by subId: {user.vpn_client_id}")
                        client = await asyncio.wait_for(
                            self.provider.get_client_by_sub_id(user.vpn_client_id),
                            timeout=10.0
                        )
                        if client:
                            logger.debug(f"Client found by subId: {client}")
                    except asyncio.TimeoutError:
                        logger.warning(f"Timeout getting client by subId for user {user_id}")
                    except Exception as e:
                        logger.warning(f"Error getting client by subId: {e}")

                # 3. Fallback – поиск по префиксу email среди всех клиентов
                if not client and email:
                    try:
                        prefix = email[:email.rfind('_')] + '_'
                        logger.debug(f"Fallback: searching all clients with prefix {prefix}")
                        all_clients = await asyncio.wait_for(
                            self.provider.get_all_clients(),
                            timeout=15.0
                        )
                        for c in all_clients:
                            if c.get("email", "").startswith(prefix):
                                client = {
                                    "uuid": c.get("id") or c.get("uuid"),
                                    "subId": c.get("subId") or c.get("subid"),
                                    "email": c.get("email"),
                                    "enable": c.get("enable"),
                                }
                                logger.info(f"Client found in fallback: {client}")
                                break
                    except asyncio.TimeoutError:
                        logger.warning(f"Timeout getting all clients for user {user_id}")
                    except Exception as e:
                        logger.exception(f"Error in fallback client search: {e}")

                # Если клиент найден – возвращаем ссылку
                if client and client.get("subId"):
                    link = self.provider.get_subscription_link(client["subId"])
                    logger.info(f"Existing key for user {user_id}: {link}")
                    return link

                # Клиент не найден – создаём новый
                if user.vpn_client_id:
                    logger.warning(f"Stored client_id {user.vpn_client_id} not found on panel, will recreate")

                days_left = (user.vpn_subscription_end - now).days
                if days_left < 1:
                    days_left = 30
                elif days_left > MAX_SUBSCRIPTION_DAYS:
                    days_left = MAX_SUBSCRIPTION_DAYS
                logger.info(f"Creating new key for user {user_id}, days_left={days_left}")

                # Передаём текущую сессию в create_key
                new_link = await self.create_key(user_id, days_left, session=session)
                if new_link:
                    # ❗️ НЕ используем session.refresh() – объект user уже обновлён в памяти
                    # Изменения сохранятся при коммите транзакции (после выхода из этого метода)
                    return new_link
                else:
                    logger.error(f"Failed to create new key for user {user_id}")
                    return None

    @retry_db_operation(max_retries=3)
    async def revoke_key(self, user_id: int) -> bool:
        """Отзывает ключ у пользователя."""
        async with AsyncSessionLocal() as session:
            async with session.begin():
                user = await get_or_create_bot_user(session, user_id)
                client_uuid = user.vpn_client_id
                if not client_uuid:
                    logger.info(f"User {user_id} has no active key to revoke")
                    return True

        # Отзыв на панели (вне БД-транзакции)
        try:
            success = await asyncio.wait_for(
                self.provider.revoke_client(client_uuid),
                timeout=15.0
            )
            if not success:
                email = f"tg_{user_id}_{client_uuid[:8]}"
                try:
                    client = await asyncio.wait_for(
                        self.provider.get_client_by_email(email),
                        timeout=10.0
                    )
                except:
                    client = None

                if client is None:
                    logger.info(f"Client {client_uuid} not found on panel, assuming already revoked")
                else:
                    logger.error(f"Failed to revoke client {client_uuid} for user {user_id}")
                    await self._notify_admin_and_user(user_id, f"не удалось отозвать ключ {client_uuid}")
                    return False
        except asyncio.TimeoutError:
            logger.error(f"Timeout revoking client {client_uuid} for user {user_id}")
            await self._notify_admin_and_user(user_id, f"таймаут при отзыве ключа {client_uuid}")
            return False
        except Exception as e:
            logger.exception(f"Error revoking client {client_uuid} for user {user_id}: {e}")
            await self._notify_admin_and_user(user_id, f"ошибка при отзыве ключа: {e}")
            return False

        # Обновляем БД
        async with AsyncSessionLocal() as session:
            async with session.begin():
                user = await get_or_create_bot_user(session, user_id)
                user.vpn_client_id = None
                user.vpn_subscription_end = datetime.now(timezone.utc) - timedelta(days=1)
                logger.info(f"Key revoked for user {user_id}")
                return True

    async def _notify_admin_and_user(self, user_id: int, error_msg: str):
        """Отправляет уведомление администратору и пользователю об ошибке."""
        from admin import send_admin_alert
        await send_admin_alert(f"⚠️ Ошибка при работе с VPN для пользователя {user_id}: {error_msg}")
        try:
            from config import TOKEN
            from aiogram import Bot
            bot = Bot(token=TOKEN)
            await bot.send_message(
                user_id,
                "Сервер временно перегружен, мы уже выдаем вам ключ, администратор уведомлен."
            )
            await bot.session.close()
        except Exception:
            pass


# Глобальный экземпляр менеджера
_vpn_manager: Optional[VPNManager] = None

def set_vpn_manager(manager: VPNManager) -> None:
    global _vpn_manager
    _vpn_manager = manager

def get_vpn_manager() -> Optional[VPNManager]:
    return _vpn_manager