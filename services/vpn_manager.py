# services/vpn_manager.py
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
import uuid

from sqlalchemy import text

from db.base import AsyncSessionLocal, retry_db_operation
from db.crud import get_or_create_bot_user
from services.vpn_provider import XUIVPNProvider

logger = logging.getLogger(__name__)

class VPNManager:
    def __init__(self, provider: XUIVPNProvider):
        self.provider = provider

    @retry_db_operation(max_retries=3)
    async def create_key(self, user_id: int, days: int) -> Optional[str]:
        client_uuid = str(uuid.uuid4())
        email = f"tg_{user_id}_{client_uuid[:8]}"

        try:
            # Таймаут 15 секунд на создание клиента
            client_data = await asyncio.wait_for(
                self.provider.create_client(email),
                timeout=15.0
            )
        except asyncio.TimeoutError:
            logger.error(f"Timeout creating client for user {user_id}")
            await self._notify_admin_and_user(user_id, "таймаут при создании клиента на панели 3x-UI")
            return None
        except Exception as e:
            logger.exception(f"Error creating client for user {user_id}: {e}")
            await self._notify_admin_and_user(user_id, f"ошибка при создании клиента: {e}")
            return None

        if not client_data:
            logger.error(f"Failed to create client for user {user_id}")
            await self._notify_admin_and_user(user_id, "не удалось создать клиента на панели")
            return None

        sub_id = client_data['subId']
        link = self.provider.get_subscription_link(sub_id)

        async with AsyncSessionLocal() as session:
            async with session.begin():
                user = await get_or_create_bot_user(session, user_id)
                user.vpn_client_id = client_uuid
                now = datetime.now(timezone.utc)
                if user.vpn_subscription_end is None or user.vpn_subscription_end <= now:
                    user.vpn_subscription_end = now + timedelta(days=days)
                else:
                    user.vpn_subscription_end += timedelta(days=days)
                logger.info(f"Key created and DB updated for user {user_id}: {link}")
                return link

    @retry_db_operation(max_retries=3)
    async def get_or_create_link(self, user_id: int) -> Optional[str]:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                user = await get_or_create_bot_user(session, user_id)
                now = datetime.now(timezone.utc)

                if user.vpn_subscription_end is None or user.vpn_subscription_end <= now:
                    logger.info(f"User {user_id} has no active subscription")
                    return None

                if user.vpn_client_id:
                    email = f"tg_{user_id}_{user.vpn_client_id[:8]}"
                    try:
                        client = await asyncio.wait_for(
                            self.provider.get_client_by_email(email),
                            timeout=10.0
                        )
                    except asyncio.TimeoutError:
                        logger.warning(f"Timeout getting client by email for user {user_id}")
                        client = None
                    except Exception as e:
                        logger.exception(f"Error getting client by email for user {user_id}: {e}")
                        client = None

                    if client and client.get("subId"):
                        link = self.provider.get_subscription_link(client["subId"])
                        logger.info(f"Existing key for user {user_id}: {link}")
                        return link
                    else:
                        logger.warning(f"Stored client_id {user.vpn_client_id} not found on panel, will recreate")
                        user.vpn_client_id = None

        days_left = (user.vpn_subscription_end - now).days
        if days_left < 1:
            days_left = 30
        return await self.create_key(user_id, days_left)

    @retry_db_operation(max_retries=3)
    async def revoke_key(self, user_id: int) -> bool:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                user = await get_or_create_bot_user(session, user_id)
                client_uuid = user.vpn_client_id
                if not client_uuid:
                    logger.info(f"User {user_id} has no active key to revoke")
                    return True

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
                except asyncio.TimeoutError:
                    logger.warning(f"Timeout checking client by email for user {user_id}")
                    client = None
                except Exception as e:
                    logger.exception(f"Error checking client by email for user {user_id}: {e}")
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

        async with AsyncSessionLocal() as session:
            async with session.begin():
                user = await get_or_create_bot_user(session, user_id)
                user.vpn_client_id = None
                user.vpn_subscription_end = datetime.now(timezone.utc) - timedelta(days=1)
                logger.info(f"Key revoked for user {user_id}")
                return True

    async def _notify_admin_and_user(self, user_id: int, error_msg: str):
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

# ---------- Глобальный экземпляр ----------
_vpn_manager: Optional[VPNManager] = None

def set_vpn_manager(manager: VPNManager) -> None:
    global _vpn_manager
    _vpn_manager = manager

def get_vpn_manager() -> Optional[VPNManager]:
    return _vpn_manager