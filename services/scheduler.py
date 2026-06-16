import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func

from db.base import AsyncSessionLocal
from db.models import BotUser
from db.crud import set_vpn_client_id, set_vpn_server_id, get_or_create_bot_user
from handlers import get_vpn_manager
from admin import send_admin_alert

logger = logging.getLogger(__name__)

async def check_expired_subscriptions(bot):
    """Проверяет истёкшие VPN-подписки и отзывает ключи с retry."""
    retry_count = 3
    try:
        while True:
            try:
                async with AsyncSessionLocal() as session:
                    now = datetime.now(timezone.utc)
                    result = await session.execute(
                        select(BotUser).where(
                            BotUser.vpn_subscription_end < now,
                            BotUser.vpn_client_id.isnot(None)
                        )
                    )
                    expired_users = result.scalars().all()

                    vpn_manager = get_vpn_manager()

                    for user in expired_users:
                        client_uuid = user.vpn_client_id
                        success = False
                        for attempt in range(retry_count):
                            try:
                                success = await vpn_manager.revoke_key(user.telegram_id)
                                if success:
                                    break
                            except Exception as e:
                                logger.warning(f"Network error revoking client {client_uuid} for user {user.telegram_id}, attempt {attempt+1}: {e}")
                                if attempt < retry_count - 1:
                                    await asyncio.sleep(2 ** attempt)
                            except Exception as e:
                                logger.error(f"Unexpected error revoking client {client_uuid}, attempt {attempt+1}: {e}")
                                break

                        if success:
                            # Клиент уже обнулён внутри revoke_key, но на всякий случай
                            user.vpn_client_id = None
                            user.server_id = None
                            await session.commit()
                            logger.info(f"Ключ {client_uuid} отозван для user_id={user.telegram_id}")
                            try:
                                await bot.send_message(
                                    user.telegram_id,
                                    "❌ Ваша VPN-подписка истекла. Для продления перейдите в раздел оплаты."
                                )
                            except Exception as e:
                                logger.error(f"Не удалось отправить уведомление пользователю {user.telegram_id}: {e}")
                        else:
                            logger.error(f"Не удалось отозвать ключ {client_uuid} для user_id={user.telegram_id} после {retry_count} попыток")
                            await send_admin_alert(f"Не удалось отозвать ключ {client_uuid} для user_id={user.telegram_id}")

            except asyncio.CancelledError:
                raise  # пробрасываем для выхода из задачи
            except Exception as e:
                logger.error(f"Ошибка в фоновой задаче проверки подписок: {e}", exc_info=True)
                await send_admin_alert(f"Ошибка в задаче проверки подписок: {e}")

            await asyncio.sleep(3600)  # раз в час
    except asyncio.CancelledError:
        logger.info("Task check_expired_subscriptions cancelled")
        raise

async def send_expiry_reminders(bot):
    """Отправляет напоминания о скором истечении подписки."""
    try:
        while True:
            try:
                async with AsyncSessionLocal() as session:
                    now = datetime.now(timezone.utc)
                    result = await session.execute(
                        select(BotUser).where(
                            BotUser.vpn_subscription_end > now,
                            BotUser.vpn_client_id.isnot(None)
                        )
                    )
                    users = result.scalars().all()

                    for user in users:
                        days_left = (user.vpn_subscription_end - now).days
                        if days_left not in (7, 3, 1):
                            continue

                        if user.last_reminder_sent and user.last_reminder_sent.date() == now.date():
                            continue

                        day_word = {7: "7 дней", 3: "3 дня", 1: "1 день"}[days_left]
                        message_sent = False
                        for attempt in range(3):
                            try:
                                await bot.send_message(
                                    user.telegram_id,
                                    f"⏰ Ваша VPN-подписка истекает через {day_word}.\n"
                                    f"Дата окончания: {user.vpn_subscription_end.strftime('%d.%m.%Y')}\n"
                                    f"Продлите её в разделе 💳 Оплатить VPN, чтобы не остаться без доступа."
                                )
                                message_sent = True
                                break
                            except Exception as e:
                                logger.warning(f"Не удалось отправить напоминание пользователю {user.telegram_id}, attempt {attempt+1}: {e}")
                                if attempt < 2:
                                    await asyncio.sleep(1)

                        if message_sent:
                            user.last_reminder_sent = now
                            await session.commit()
                            logger.info(f"Отправлено напоминание за {days_left} дн. пользователю {user.telegram_id}")
                        else:
                            logger.error(f"Не удалось отправить напоминание пользователю {user.telegram_id} после 3 попыток")

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Ошибка в задаче напоминаний: {e}", exc_info=True)

            await asyncio.sleep(3600)  # раз в час
    except asyncio.CancelledError:
        logger.info("Task send_expiry_reminders cancelled")
        raise

async def start_scheduler(bot):
    """Запускает обе фоновые задачи и возвращает их для управления."""
    task1 = asyncio.create_task(check_expired_subscriptions(bot))
    task2 = asyncio.create_task(send_expiry_reminders(bot))
    logger.info("Фоновые задачи проверки подписок и напоминаний запущены")
    return [task1, task2]