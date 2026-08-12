# services/vpn_manager.py
import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

from db.base import AsyncSessionLocal, retry_db_operation
from db.crud import get_or_create_bot_user
from services.redis_service import redis_service
from services.vpn_provider import XUIVPNProvider

logger = logging.getLogger(__name__)
MAX_SUBSCRIPTION_DAYS = 96 * 365


class VPNManager:
    def __init__(self, provider: XUIVPNProvider):
        self.provider = provider

    # ---- Вспомогательные методы для Redis ----
    async def _get_cached_link(self, user_id: int) -> str | None:
        key = f"vpn_link:{user_id}"
        return await redis_service.get_cache(key)

    async def _set_cached_link(self, user_id: int, link: str):
        key = f"vpn_link:{user_id}"
        await redis_service.set_cache(key, link)

    async def _invalidate_cache(self, user_id: int):
        key = f"vpn_link:{user_id}"
        await redis_service.delete_cache(key)
        logger.debug(f"Cache invalidated for user {user_id}")

    # ---- Основные методы ----
    @retry_db_operation(max_retries=3)
    async def create_key(self, user_id: int, days: int, session=None) -> str | None:
        if days > MAX_SUBSCRIPTION_DAYS:
            logger.warning(
                f"Requested {days} days for user {user_id}, capped to {MAX_SUBSCRIPTION_DAYS}"
            )
            days = MAX_SUBSCRIPTION_DAYS

        client_uuid = str(uuid.uuid4())
        email = f"tg_{user_id}_{client_uuid[:8]}"
        sub_id = client_uuid[:16]
        logger.info(f"Creating key: user={user_id}, email={email}, sub_id={sub_id}")

        try:
            client_data = await asyncio.wait_for(
                self.provider.create_client(email, sub_id), timeout=15.0
            )
        except asyncio.TimeoutError:
            logger.error(f"Timeout creating client for user {user_id}")
            await self._notify_admin_and_user(
                user_id, "таймаут при создании клиента на панели"
            )
            return None
        except Exception as e:
            logger.exception(f"Error creating client for user {user_id}: {e}")
            await self._notify_admin_and_user(
                user_id, f"ошибка при создании клиента: {e}"
            )
            return None

        if not client_data:
            logger.error(f"Failed to create client for user {user_id}")
            await self._notify_admin_and_user(
                user_id, "не удалось создать клиента на панели"
            )
            return None

        sub_id = client_data.get("subId", sub_id)
        link = self.provider.get_subscription_link(sub_id)

        if session is None:
            async with AsyncSessionLocal() as sess, sess.begin():
                user = await get_or_create_bot_user(sess, user_id)
                self._update_user_object(user, client_uuid, link, days)
        else:
            user = await get_or_create_bot_user(session, user_id)
            self._update_user_object(user, client_uuid, link, days)

        return link

    def _update_user_object(self, user, client_uuid: str, link: str, days: int):
        user.vpn_client_id = client_uuid
        now = datetime.now(timezone.utc)
        if user.vpn_subscription_end is None or user.vpn_subscription_end <= now:
            new_end = now + timedelta(days=days)
        else:
            new_end = user.vpn_subscription_end + timedelta(days=days)
        max_allowed = now + timedelta(days=MAX_SUBSCRIPTION_DAYS)
        if new_end > max_allowed:
            new_end = max_allowed
            logger.warning(
                f"Capped subscription end for user {user.telegram_id} to {max_allowed}"
            )
        user.vpn_subscription_end = new_end
        logger.info(
            f"Updated user {user.telegram_id}: client_id={client_uuid}, end={new_end}"
        )

    @retry_db_operation(max_retries=3)
    async def get_or_create_link(self, user_id: int) -> str | None:
        # 1. Проверяем кэш в Redis
        cached_link = await self._get_cached_link(user_id)
        if cached_link:
            logger.info(f"Returning cached link for user {user_id}")
            return cached_link

        logger.info(f"get_or_create_link called for user {user_id}")
        async with AsyncSessionLocal() as session:
            async with session.begin():
                user = await get_or_create_bot_user(session, user_id)
                now = datetime.now(timezone.utc)

                if (
                    user.vpn_subscription_end is None
                    or user.vpn_subscription_end <= now
                ):
                    logger.info(f"User {user_id} has no active subscription")
                    return None

                email = None
                if user.vpn_client_id:
                    email = f"tg_{user_id}_{user.vpn_client_id[:8]}"

                client = None

                # 2. Поиск по email
                if email:
                    try:
                        logger.debug(f"Checking client by email: {email}")
                        client = await asyncio.wait_for(
                            self.provider.get_client_by_email(email), timeout=5.0
                        )
                        if client:
                            logger.debug(f"Client found by email: {client}")
                    except asyncio.TimeoutError:
                        logger.warning(
                            f"Timeout getting client by email for user {user_id}"
                        )
                    except Exception as e:
                        logger.exception(
                            f"Error getting client by email for user {user_id}: {e}"
                        )

                # 3. Если по email не найден – пробуем по subId (обрезанный до 16 символов)
                if not client and user.vpn_client_id:
                    sub_id_to_search = user.vpn_client_id[:16]
                    try:
                        logger.debug(
                            f"Trying to find client by subId: {sub_id_to_search}"
                        )
                        client = await asyncio.wait_for(
                            self.provider.get_client_by_sub_id(sub_id_to_search),
                            timeout=5.0,
                        )
                        if client:
                            logger.debug(f"Client found by subId: {client}")
                    except asyncio.TimeoutError:
                        logger.warning(
                            f"Timeout getting client by subId for user {user_id}"
                        )
                    except Exception as e:
                        logger.warning(f"Error getting client by subId: {e}")

                if client and client.get("subId"):
                    link = self.provider.get_subscription_link(client["subId"])
                    logger.info(f"Existing key for user {user_id}: {link}")
                    await self._set_cached_link(user_id, link)
                    return link

                # 4. Клиент не найден – инвалидируем кэш и создаём новый
                if user.vpn_client_id:
                    logger.warning(
                        f"Stored client_id {user.vpn_client_id} not found on panel, will recreate"
                    )
                    await self._invalidate_cache(user_id)

                days_left = (user.vpn_subscription_end - now).days
                if days_left < 1:
                    days_left = 30
                elif days_left > MAX_SUBSCRIPTION_DAYS:
                    days_left = MAX_SUBSCRIPTION_DAYS
                logger.info(
                    f"Creating new key for user {user_id}, days_left={days_left}"
                )

                new_link = await self.create_key(user_id, days_left, session=session)
                if new_link:
                    await self._set_cached_link(user_id, new_link)
                    return new_link
                else:
                    logger.error(f"Failed to create new key for user {user_id}")
                    return None

    @retry_db_operation(max_retries=3)
    async def revoke_key(self, user_id: int) -> bool:
        # Инвалидируем кэш при отзыве
        await self._invalidate_cache(user_id)

        async with AsyncSessionLocal() as session, session.begin():
            user = await get_or_create_bot_user(session, user_id)
            client_uuid = user.vpn_client_id
            if not client_uuid:
                logger.info(f"User {user_id} has no active key to revoke")
                return True

        try:
            success = await asyncio.wait_for(
                self.provider.revoke_client(client_uuid), timeout=15.0
            )
            if not success:
                email = f"tg_{user_id}_{client_uuid[:8]}"
                try:
                    client = await asyncio.wait_for(
                        self.provider.get_client_by_email(email), timeout=10.0
                    )
                except:
                    client = None

                if client is None:
                    logger.info(
                        f"Client {client_uuid} not found on panel, assuming already revoked"
                    )
                else:
                    logger.error(
                        f"Failed to revoke client {client_uuid} for user {user_id}"
                    )
                    await self._notify_admin_and_user(
                        user_id, f"не удалось отозвать ключ {client_uuid}"
                    )
                    return False
        except asyncio.TimeoutError:
            logger.error(f"Timeout revoking client {client_uuid} for user {user_id}")
            await self._notify_admin_and_user(
                user_id, f"таймаут при отзыве ключа {client_uuid}"
            )
            return False
        except Exception as e:
            logger.exception(
                f"Error revoking client {client_uuid} for user {user_id}: {e}"
            )
            await self._notify_admin_and_user(user_id, f"ошибка при отзыве ключа: {e}")
            return False

        async with AsyncSessionLocal() as session, session.begin():
            user = await get_or_create_bot_user(session, user_id)
            user.vpn_client_id = None
            user.vpn_subscription_end = datetime.now(timezone.utc) - timedelta(days=1)
            logger.info(f"Key revoked for user {user_id}")
            return True

    async def _notify_admin_and_user(self, user_id: int, error_msg: str):
        from admin import send_admin_alert

        await send_admin_alert(
            f"⚠️ Ошибка при работе с VPN для пользователя {user_id}: {error_msg}"
        )
        try:
            from aiogram import Bot

            from config import TOKEN

            bot = Bot(token=TOKEN)
            await bot.send_message(
                user_id,
                "Сервер временно перегружен, мы уже выдаем вам ключ, администратор уведомлен.",
            )
            await bot.session.close()
        except Exception as e:
            logger.warning(f"Error closing temporary bot session: {e}")


_vpn_manager: VPNManager | None = None


def set_vpn_manager(manager: VPNManager) -> None:
    global _vpn_manager
    _vpn_manager = manager


def get_vpn_manager() -> VPNManager | None:
    return _vpn_manager
