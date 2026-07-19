# services/vpn_manager.py
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
import uuid

from sqlalchemy import select

from db.base import AsyncSessionLocal, retry_db_operation
from db.crud import get_or_create_bot_user
from db.models import BotUser
from services.vpn_provider import XUIVPNProvider

logger = logging.getLogger(__name__)

class VPNManager:
    def __init__(self, provider: XUIVPNProvider):
        self.provider = provider

    @retry_db_operation(max_retries=3)
    async def create_key(self, user_id: int, days: int) -> Optional[str]:
        """
        Создаёт нового клиента на панели и возвращает ссылку.
        В БД сохраняется subId (первые 16 символов UUID) как vpn_client_id.
        """
        sub_id = str(uuid.uuid4())[:16]  # генерируем стабильный subId
        email = f"tg_{user_id}_{sub_id[:8]}"

        try:
            client_data = await asyncio.wait_for(
                self.provider.create_client(email, sub_id),
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

        # sub_id уже есть, получаем ссылку
        link = self.provider.get_subscription_link(sub_id)

        async with AsyncSessionLocal() as session:
            async with session.begin():
                user = await get_or_create_bot_user(session, user_id)
                user.vpn_client_id = sub_id  # сохраняем subId, а не UUID клиента
                now = datetime.now(timezone.utc)
                if user.vpn_subscription_end is None or user.vpn_subscription_end <= now:
                    user.vpn_subscription_end = now + timedelta(days=days)
                else:
                    user.vpn_subscription_end += timedelta(days=days)
                logger.info(f"Key created and DB updated for user {user_id}: {link}")
                return link

    @retry_db_operation(max_retries=3)
    async def get_or_create_link(self, user_id: int) -> Optional[str]:
        """
        Возвращает существующую ссылку или создаёт новую, если ключ отсутствует.
        Гарантирует атомарность через блокировку строки БД.
        """
        async with AsyncSessionLocal() as session:
            async with session.begin():
                stmt = select(BotUser).where(BotUser.telegram_id == user_id).with_for_update()
                user = (await session.execute(stmt)).scalar_one_or_none()
                if not user:
                    user = BotUser(telegram_id=user_id)
                    session.add(user)
                    await session.flush()
                    stmt = select(BotUser).where(BotUser.telegram_id == user_id).with_for_update()
                    user = (await session.execute(stmt)).scalar_one()

                now = datetime.now(timezone.utc)
                if user.vpn_subscription_end is None or user.vpn_subscription_end <= now:
                    logger.info(f"User {user_id} has no active subscription")
                    return None

                # Если есть subId – сразу возвращаем ссылку, не обращаясь к панели
                if user.vpn_client_id:
                    link = self.provider.get_subscription_link(user.vpn_client_id)
                    logger.info(f"Existing key for user {user_id}: {link}")
                    return link

                # Если subId нет – создаём новый ключ
                sub_id = str(uuid.uuid4())[:16]
                email = f"tg_{user_id}_{sub_id[:8]}"
                try:
                    client_data = await asyncio.wait_for(
                        self.provider.create_client(email, sub_id),
                        timeout=15.0
                    )
                except (asyncio.TimeoutError, Exception) as e:
                    logger.error(f"Error creating client for user {user_id}: {e}")
                    return None

                if not client_data:
                    logger.error(f"Failed to create client for user {user_id}")
                    return None

                link = self.provider.get_subscription_link(sub_id)
                user.vpn_client_id = sub_id
                logger.info(f"Key created and DB updated for user {user_id}: {link}")
                return link

    @retry_db_operation(max_retries=3)
    async def revoke_key(self, user_id: int) -> bool:
        """
        Отзывает ключ пользователя.
        Использует subId, хранящийся в БД, для удаления через /delSub/{subId}.
        """
        async with AsyncSessionLocal() as session:
            async with session.begin():
                user = await get_or_create_bot_user(session, user_id)
                sub_id = user.vpn_client_id
                if not sub_id:
                    logger.info(f"User {user_id} has no active key to revoke")
                    return True

        try:
            success = await asyncio.wait_for(
                self.provider.revoke_client(sub_id),
                timeout=15.0
            )
            if not success:
                logger.error(f"Failed to revoke client with subId {sub_id} for user {user_id}")
                await self._notify_admin_and_user(user_id, f"не удалось отозвать ключ {sub_id}")
                return False
        except asyncio.TimeoutError:
            logger.error(f"Timeout revoking client with subId {sub_id} for user {user_id}")
            await self._notify_admin_and_user(user_id, f"таймаут при отзыве ключа {sub_id}")
            return False
        except Exception as e:
            logger.exception(f"Error revoking client with subId {sub_id} for user {user_id}: {e}")
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