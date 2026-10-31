# services/vpn_manager.py
import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

from db.base import AsyncSessionLocal, retry_db_operation
from db.crud import get_or_create_bot_user, update_vpn_subscription
from services.redis_service import redis_service
from services.vpn_provider import XUIVPNProvider

logger = logging.getLogger(__name__)


class VPNManager:
    def __init__(self, provider: XUIVPNProvider):
        self.provider = provider

    # ---- Вспомогательные методы для Redis ----
    async def _get_cached_link(self, user_id: int) -> str | None:
        return await redis_service.get_cache(f"vpn_link:{user_id}")

    async def _set_cached_link(self, user_id: int, link: str) -> None:
        await redis_service.set_cache(f"vpn_link:{user_id}", link)

    async def _invalidate_cache(self, user_id: int) -> None:
        await redis_service.delete_cache(f"vpn_link:{user_id}")
        logger.debug(f"Cache invalidated for user {user_id}")

    # ---- Создание ключа (НЕ трогает дату окончания подписки!) ----
    @retry_db_operation(max_retries=3)
    async def create_vpn_key(self, user_id: int, session=None) -> str | None:
        """Создаёт клиента на VPN-панели и сохраняет vpn_client_id.

        ВАЖНО: не изменяет vpn_subscription_end. Продление подписки —
        ответственность activate_subscription / update_vpn_subscription.
        """
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

        real_sub_id = client_data.get("subId", sub_id)
        link = self.provider.get_subscription_link(real_sub_id)

        if session is None:
            async with AsyncSessionLocal() as sess, sess.begin():
                user = await get_or_create_bot_user(sess, user_id)
                user.vpn_client_id = client_uuid
        else:
            user = await get_or_create_bot_user(session, user_id)
            user.vpn_client_id = client_uuid

        logger.info(f"Key created for user {user_id}: client_id={client_uuid}")
        return link

    # ---- Выдача подписки админом: продлить + создать ключ ----
    @retry_db_operation(max_retries=3)
    async def grant_subscription(self, user_id: int, days: int) -> str | None:
        """Продлевает подписку на `days` и создаёт ключ. Для /grant."""
        async with AsyncSessionLocal() as session, session.begin():
            await get_or_create_bot_user(session, user_id)  # создаём если нет
            ok = await update_vpn_subscription(session, user_id, days)
        if not ok:
            logger.error(f"grant_subscription: could not update subscription for {user_id}")
            return None

        return await self.create_vpn_key(user_id)

    # ---- Получение или создание ссылки ----
    @retry_db_operation(max_retries=3)
    async def get_or_create_link(self, user_id: int) -> str | None:
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

                if email:
                    try:
                        logger.debug(f"Checking client by email: {email}")
                        client = await asyncio.wait_for(
                            self.provider.get_client_by_email(email), timeout=5.0
                        )
                    except asyncio.TimeoutError:
                        logger.warning(
                            f"Timeout getting client by email for user {user_id}"
                        )
                    except Exception as e:
                        logger.exception(
                            f"Error getting client by email for user {user_id}: {e}"
                        )

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

                if user.vpn_client_id:
                    logger.warning(
                        f"Stored client_id {user.vpn_client_id} not found on panel, will recreate"
                    )
                    await self._invalidate_cache(user_id)

                # ВАЖНО: дни не передаём, подписку не продлеваем
                new_link = await self.create_vpn_key(user_id, session=session)
                if new_link:
                    await self._set_cached_link(user_id, new_link)
                    return new_link

                logger.error(f"Failed to create new key for user {user_id}")
                return None

    # ---- Отзыв ключа ----
    @retry_db_operation(max_retries=3)
    async def revoke_key(self, user_id: int) -> bool:
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
                except Exception:
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

    async def _notify_admin_and_user(self, user_id: int, error_msg: str) -> None:
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