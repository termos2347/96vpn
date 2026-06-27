import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func
from aiogram.exceptions import TelegramForbiddenError

from db.base import AsyncSessionLocal
from db.models import BotUser
from db.crud import set_vpn_client_id, set_vpn_server_id, get_or_create_bot_user
from handlers import get_server_pool, get_vpn_manager
from admin import send_admin_alert
from admin.bot import log_error  # <-- добавлен импорт

logger = logging.getLogger(__name__)

async def check_expired_subscriptions(bot):
    """Проверяет истёкшие VPN-подписки и отзывает ключи с retry."""
    retry_count = 3

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

                if not expired_users:
                    logger.debug("Нет истёкших подписок для отзыва")
                else:
                    logger.info(f"Найдено {len(expired_users)} истёкших подписок для отзыва")
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
                                logger.warning(
                                    f"Ошибка при отзыве ключа {client_uuid} для user_id={user.telegram_id}, "
                                    f"попытка {attempt+1}/{retry_count}: {e}"
                                )
                                if attempt < retry_count - 1:
                                    await asyncio.sleep(2 ** attempt)

                        if success:
                            logger.info(f"Ключ {client_uuid} отозван для user_id={user.telegram_id}")
                            try:
                                await bot.send_message(
                                    user.telegram_id,
                                    "❌ Ваша VPN-подписка истекла. Для продления перейдите в раздел оплаты."
                                )
                            except TelegramForbiddenError:
                                logger.info(f"User {user.telegram_id} blocked the bot, skipping notification")
                            except Exception as e:
                                logger.error(f"Не удалось отправить уведомление пользователю {user.telegram_id}: {e}")
                        else:
                            logger.error(
                                f"Не удалось отозвать ключ {client_uuid} для user_id={user.telegram_id} "
                                f"после {retry_count} попыток"
                            )
                            await send_admin_alert(
                                f"Не удалось отозвать ключ {client_uuid} для user_id={user.telegram_id}"
                            )

            await asyncio.sleep(3600)

        except asyncio.CancelledError:
            logger.info("Task check_expired_subscriptions cancelled")
            raise
        except Exception as e:
            error_text = f"Critical error in check_expired_subscriptions: {e}"
            logger.error(error_text, exc_info=True)
            log_error(error_text, notify_admin=True)  # <-- добавлен log_error
            await asyncio.sleep(60)

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
                            except TelegramForbiddenError:
                                logger.info(f"User {user.telegram_id} blocked the bot, skipping reminders")
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
                error_text = f"Error in send_expiry_reminders: {e}"
                logger.error(error_text, exc_info=True)
                log_error(error_text, notify_admin=True)  # <-- добавлен log_error

            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        logger.info("Task send_expiry_reminders cancelled")
        raise

async def refresh_server_pool_periodically(interval_seconds: int = 1800):
    """
    Фоновая задача: периодически обновляет пул серверов из БД,
    пересоздаёт провайдеров и выполняет повторный логин.
    """
    while True:
        try:
            logger.info("🔄 Scheduled server pool refresh started")
            pool = get_server_pool()
            await pool.refresh_servers(wait_for_login=True, login_timeout=10.0)
            logger.info("✅ Server pool refreshed successfully")
        except asyncio.CancelledError:
            logger.info("Task refresh_server_pool_periodically cancelled")
            raise
        except Exception as e:
            error_text = f"Error refreshing server pool: {e}"
            logger.error(error_text, exc_info=True)
            log_error(error_text, notify_admin=True)  # <-- добавлен log_error

        await asyncio.sleep(interval_seconds)

async def start_scheduler(bot):
    """Запускает все фоновые задачи и возвращает их для управления."""
    task1 = asyncio.create_task(check_expired_subscriptions(bot))
    task2 = asyncio.create_task(send_expiry_reminders(bot))
    task3 = asyncio.create_task(refresh_server_pool_periodically(interval_seconds=1800))
    logger.info("Фоновые задачи запущены: проверка подписок, напоминания, обновление пула серверов")
    return [task1, task2, task3]