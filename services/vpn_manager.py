# services/vpn_manager.py
import asyncio
import logging
import uuid
import weakref
from datetime import datetime, timedelta, timezone

from config import settings
from db.base import AsyncSessionLocal, retry_db_operation
from db.crud import get_or_create_bot_user, update_vpn_subscription
from services.redis_service import redis_service
from services.vpn_provider import XUIVPNProvider
from utils.cache import clear_cache as local_clear_cache
from utils.cache import get_cache as local_get_cache
from utils.cache import set_cache as local_set_cache

logger = logging.getLogger(__name__)

_user_locks: "weakref.WeakValueDictionary[int, asyncio.Lock]" = (
    weakref.WeakValueDictionary()
)


def _get_user_lock(user_id: int) -> asyncio.Lock:
    lock = _user_locks.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        _user_locks[user_id] = lock
    return lock


class VPNManager:
    def __init__(self, provider: XUIVPNProvider):
        self.provider = provider

    # ---- Кэш ссылок: Redis + in-memory fallback ----
    async def _get_cached_link(self, user_id: int) -> str | None:
        key = f"vpn_link:{user_id}"
        redis_link = await redis_service.get_cache(key)
        if redis_link:
            return redis_link
        return local_get_cache(key)

    async def _set_cached_link(self, user_id: int, link: str) -> None:
        key = f"vpn_link:{user_id}"
        ok = await redis_service.set_cache(key, link)
        if not ok:
            local_set_cache(
                key, link, ttl_seconds=settings.REDIS_CACHE_TTL
            )

    async def _invalidate_cache(self, user_id: int) -> None:
        key = f"vpn_link:{user_id}"
        await redis_service.delete_cache(key)
        local_clear_cache(key)
        logger.debug(f"Cache invalidated for user {user_id}")

    # ---- Поиск существующего клиента на панели ----
    async def _find_existing_client(
        self, user_id: int, vpn_client_id: str | None
    ) -> dict | None:
        if not vpn_client_id:
            return None

        email = f"tg_{user_id}_{vpn_client_id[:8]}"
        try:
            client = await asyncio.wait_for(
                self.provider.get_client_by_email(email), timeout=5.0
            )
        except Exception:
            client = None
        if client and client.get("subId"):
            return client

        try:
            client = await asyncio.wait_for(
                self.provider.get_client_by_sub_id(vpn_client_id[:16]), timeout=5.0
            )
        except Exception:
            client = None
        if client and client.get("subId"):
            return client

        return None

    # ---- Сохранение client_id (retry только на БД-часть) ----
    @retry_db_operation(max_retries=3)
    async def _save_client_id(self, user_id: int, client_uuid: str) -> None:
        async with AsyncSessionLocal() as sess, sess.begin():
            user = await get_or_create_bot_user(sess, user_id)
            user.vpn_client_id = client_uuid

    # ---- Идемпотентное создание ключа (с per-user lock) ----
    async def create_vpn_key(self, user_id: int) -> str | None:
        async with _get_user_lock(user_id):
            return await self._create_vpn_key_locked(user_id)

    async def _create_vpn_key_locked(self, user_id: int) -> str | None:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                user = await get_or_create_bot_user(session, user_id)
                existing_client_id = user.vpn_client_id

        existing = await self._find_existing_client(user_id, existing_client_id)
        if existing:
            link = self.provider.get_subscription_link(existing["subId"])
            logger.info(
                f"create_vpn_key: reusing existing key for user {user_id}"
            )
            return link

        client_uuid = str(uuid.uuid4())
        email = f"tg_{user_id}_{client_uuid[:8]}"
        sub_id = client_uuid[:16]
        logger.info(
            f"Creating key: user={user_id}, email={email}, sub_id={sub_id}"
        )

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

        try:
            await self._save_client_id(user_id, client_uuid)
        except Exception as e:
            logger.exception(
                f"Failed to save client_id for user {user_id}: {e}"
            )
            await self._notify_admin_and_user(
                user_id, f"ключ создан, но client_id не сохранён в БД: {e}"
            )
            return link

        logger.info(f"Key created for user {user_id}: client_id={client_uuid}")
        return link

    # ---- Выдача подписки админом ----
    async def grant_subscription(self, user_id: int, days: int) -> str | None:
        async with AsyncSessionLocal() as session, session.begin():
            await get_or_create_bot_user(session, user_id)
            ok = await update_vpn_subscription(session, user_id, days)
        if not ok:
            logger.error(
                f"grant_subscription: could not update subscription for {user_id}"
            )
            return None

        return await self.get_or_create_link(user_id)

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
                vpn_client_id = user.vpn_client_id
                vpn_end = user.vpn_subscription_end

        if vpn_end is None or vpn_end <= datetime.now(timezone.utc):
            logger.info(f"User {user_id} has no active subscription")
            return None

        existing = await self._find_existing_client(user_id, vpn_client_id)
        if existing:
            link = self.provider.get_subscription_link(existing["subId"])
            logger.info(f"Existing key for user {user_id}: {link}")
            await self._set_cached_link(user_id, link)
            return link

        if vpn_client_id:
            logger.warning(
                f"Stored client_id {vpn_client_id} not found on panel, will recreate"
            )
            await self._invalidate_cache(user_id)

        new_link = await self.create_vpn_key(user_id)
        if new_link:
            await self._set_cached_link(user_id, new_link)
            return new_link

        logger.error(f"Failed to create new key for user {user_id}")
        return None

    # ---- Отзыв ключа ----
    @retry_db_operation(max_retries=3)
    async def revoke_key(
        self, user_id: int, require_expired: bool = False
    ) -> bool | None:
        """Отзывает ключ пользователя.

        require_expired=False (по умолчанию) — принудительный отзыв
            (админ-команда). Не проверяет статус подписки.
        require_expired=True — используется шедулером: блокирует строку
            и отзывает ключ только если подписка ДЕЙСТВИТЕЛЬНО истекла.
            Если подписку успели продлить между выборкой шедулера и
            вызовом revoke_key — возвращает None (пропуск), ключ не
            трогается.

        Возвращает:
            True  — ключ отозван (или его не было).
            False — ошибка отзыва.
            None  — пропущено, т.к. подписка ещё активна (только при
                    require_expired=True).
        """
        await self._invalidate_cache(user_id)

        async with AsyncSessionLocal() as session, session.begin():
            user = await get_or_create_bot_user(
                session, user_id, for_update=True
            )
            client_uuid = user.vpn_client_id
            if not client_uuid:
                logger.info(f"User {user_id} has no active key to revoke")
                return True

            if require_expired:
                end = user.vpn_subscription_end
                if end is None or end > datetime.now(timezone.utc):
                    logger.info(
                        f"revoke_key: user {user_id} subscription renewed, "
                        f"skipping revoke"
                    )
                    return None

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
                        f"Client {client_uuid} not found on panel, "
                        f"assuming already revoked"
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
            logger.error(
                f"Timeout revoking client {client_uuid} for user {user_id}"
            )
            await self._notify_admin_and_user(
                user_id, f"таймаут при отзыве ключа {client_uuid}"
            )
            return False
        except Exception as e:
            logger.exception(
                f"Error revoking client {client_uuid} for user {user_id}: {e}"
            )
            await self._notify_admin_and_user(
                user_id, f"ошибка при отзыве ключа: {e}"
            )
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
            from admin import bot as admin_module

            bot = getattr(admin_module, "main_bot", None)
            if bot is not None:
                try:
                    await bot.send_message(
                        user_id,
                        "Сервер временно перегружен, мы уже выдаем вам ключ, "
                        "администратор уведомлен.",
                    )
                except Exception as e:
                    logger.warning(f"Error sending user notification: {e}")
                return

            from aiogram import Bot

            from config import TOKEN

            temp_bot = Bot(token=TOKEN)
            try:
                await temp_bot.send_message(
                    user_id,
                    "Сервер временно перегружен, мы уже выдаем вам ключ, "
                    "администратор уведомлен.",
                )
            finally:
                await temp_bot.session.close()
        except Exception as e:
            logger.warning(f"Error notifying user {user_id}: {e}")


_vpn_manager: VPNManager | None = None


def set_vpn_manager(manager: VPNManager) -> None:
    global _vpn_manager
    _vpn_manager = manager


def get_vpn_manager() -> VPNManager | None:
    return _vpn_manager