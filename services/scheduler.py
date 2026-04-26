import asyncio
import logging
from datetime import datetime, timedelta
from db.base import AsyncSessionLocal
from db.models import User
from db.crud import set_vpn_client_id
from services.vpn_provider import XUIVPNProvider
from sqlalchemy import select, update

logger = logging.getLogger(__name__)
vpn_provider = XUIVPNProvider()

import asyncio
import logging
from datetime import datetime, timedelta
from db.base import AsyncSessionLocal
from db.models import User
from db.crud import set_vpn_client_id
from services.vpn_provider import XUIVPNProvider
from sqlalchemy import select, update

logger = logging.getLogger(__name__)
vpn_provider = XUIVPNProvider()

async def check_expired_subscriptions(bot):
    """Проверяет истёкшие подписки и отзывает ключи с retry."""
    retry_count = 3
    while True:
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(User).where(
                        User.vpn_subscription_end < datetime.now(),
                        User.vpn_client_id.isnot(None)
                    )
                )
                expired_users = result.scalars().all()

                for user in expired_users:
                    client_uuid = user.vpn_client_id
                    success = False
                    for attempt in range(retry_count):
                        try:
                            success = await vpn_provider.revoke_client(client_uuid)
                            if success:
                                break
                        except Exception as e:
                            logger.warning(f"Network error revoking client {client_uuid}, attempt {attempt+1}: {e}")
                            if attempt < retry_count - 1:
                                await asyncio.sleep(2 ** attempt)  # exponential backoff
                        except Exception as e:
                            logger.error(f"Unexpected error revoking client {client_uuid}, attempt {attempt+1}: {e}")
                            break

                    if success:
                        user.vpn_client_id = None
                        await session.commit()
                        logger.info(f"Ключ {client_uuid} отозван для user_id={user.user_id}")
                        try:
                            await bot.send_message(
                                user.user_id,
                                "❌ Ваша VPN-подписка истекла. Для продления перейдите в раздел оплаты."
                            )
                        except Exception as e:
                            logger.error(f"Не удалось отправить уведомление пользователю {user.user_id}: {e}")
                    else:
                        logger.error(f"Не удалось отозвать ключ {client_uuid} для user_id={user.user_id} после {retry_count} попыток")
        except Exception as e:
            logger.error(f"Ошибка в фоновой задаче проверки подписок: {e}", exc_info=True)

        await asyncio.sleep(3600)

async def send_expiry_reminders(bot):
    """Отправляет напоминания о скором истечении подписки (за 7, 3, 1 день) с retry."""
    while True:
        try:
            async with AsyncSessionLocal() as session:
                now = datetime.utcnow()
                # Выбираем всех, у кого подписка ещё активна и есть ключ
                result = await session.execute(
                    select(User).where(
                        User.vpn_subscription_end > now,
                        User.vpn_client_id.isnot(None)
                    )
                )
                users = result.scalars().all()

                for user in users:
                    days_left = (user.vpn_subscription_end - now).days
                    if days_left not in (7, 3, 1):
                        continue

                    # Проверяем, не отправляли ли уже сегодня
                    if user.last_reminder_sent and user.last_reminder_sent.date() == now.date():
                        continue

                    # Отправляем уведомление с retry
                    day_word = {7: "7 дней", 3: "3 дня", 1: "1 день"}[days_left]
                    message_sent = False
                    for attempt in range(3):
                        try:
                            await bot.send_message(
                                user.user_id,
                                f"⏰ Ваша VPN-подписка истекает через {day_word}.\n"
                                f"Дата окончания: {user.vpn_subscription_end.strftime('%d.%m.%Y')}\n"
                                f"Продлите её в разделе 💳 Оплатить VPN, чтобы не остаться без доступа."
                            )
                            message_sent = True
                            break
                        except Exception as e:
                            logger.warning(f"Не удалось отправить напоминание пользователю {user.user_id}, attempt {attempt+1}: {e}")
                            if attempt < 2:
                                await asyncio.sleep(1)

                    if message_sent:
                        # Фиксируем отправку
                        user.last_reminder_sent = now
                        await session.commit()
                        logger.info(f"Отправлено напоминание за {days_left} дн. пользователю {user.user_id}")
                    else:
                        logger.error(f"Не удалось отправить напоминание пользователю {user.user_id} после 3 попыток")

        except Exception as e:
            logger.error(f"Ошибка в задаче напоминаний: {e}", exc_info=True)

        await asyncio.sleep(3600)  # проверяем раз в час

async def start_scheduler(bot):
    """Запускает обе фоновые задачи."""
    asyncio.create_task(check_expired_subscriptions(bot))
    asyncio.create_task(send_expiry_reminders(bot))
    logger.info("Фоновые задачи проверки подписок и напоминаний запущены")