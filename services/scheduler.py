# services/scheduler.py
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from aiogram.exceptions import TelegramForbiddenError

from db.base import AsyncSessionLocal, retry_db_operation
from db.models import BotUser
from handlers import get_vpn_manager, get_server_pool
from admin import send_admin_alert
from admin.bot import log_error

logger = logging.getLogger(__name__)

async def run_with_restart(coro, task_name: str, restart_delay: int = 5):
    """
    Запускает корутину coro() в бесконечном цикле с автоматическим перезапуском при падении.
    При CancelledError – завершается без перезапуска.
    """
    while True:
        try:
            await coro()
        except asyncio.CancelledError:
            logger.info(f"Task {task_name} cancelled")
            raise
        except Exception as e:
            logger.error(f"Task {task_name} crashed: {e}", exc_info=True)
            await send_admin_alert(f"❌ Фоновая задача {task_name} упала: {e}. Будет перезапущена через {restart_delay}с.")
            await asyncio.sleep(restart_delay)
        else:
            # Если задача завершилась без ошибок (чего не должно быть), перезапускаем
            logger.warning(f"Task {task_name} finished unexpectedly, restarting in {restart_delay}s")
            await asyncio.sleep(restart_delay)

@retry_db_operation(max_retries=3)
async def check_expired_subscriptions(bot):
    """Проверяет истёкшие VPN-подписки и отзывает ключи (один проход)."""
    retry_count = 3
    try:
        async with AsyncSessionLocal() as session:
            now = datetime.now(timezone.utc)

            stmt = (
                select(BotUser)
                .where(
                    BotUser.vpn_subscription_end < now,
                    BotUser.vpn_client_id.isnot(None)
                )
                .with_for_update()  # блокируем строки
            )
            result = await session.execute(stmt)
            expired_users = result.scalars().all()

            if not expired_users:
                logger.debug("Нет истёкших подписок для отзыва")
                return

            logger.info(f"Найдено {len(expired_users)} истёкших подписок для отзыва (заблокированы)")
            vpn_manager = get_vpn_manager()

            for user in expired_users:
                if user.vpn_subscription_end >= now:
                    logger.info(f"Пользователь {user.telegram_id} продлил подписку, пропускаем")
                    continue

                client_uuid = user.vpn_client_id
                success = False
                for attempt in range(retry_count):
                    try:
                        success = await vpn_manager._revoke_key_unsafe(user.telegram_id, session)
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

    except Exception as e:
        logger.exception(f"Ошибка в check_expired_subscriptions: {e}")
        raise

@retry_db_operation(max_retries=3)
async def send_expiry_reminders(bot):
    """Отправляет напоминания о скором истечении подписки (один проход)."""
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
    except Exception as e:
        logger.exception(f"Ошибка в send_expiry_reminders: {e}")
        raise

@retry_db_operation(max_retries=3)
async def refresh_server_pool_periodically():
    """Обновляет пул серверов из БД (один проход, вызывается по расписанию)."""
    try:
        logger.info("🔄 Scheduled server pool refresh started")
        pool = get_server_pool()
        await pool.refresh_servers(wait_for_login=True, login_timeout=10.0)
        logger.info("✅ Server pool refreshed successfully")
    except Exception as e:
        logger.exception(f"Ошибка при обновлении пула серверов: {e}")
        raise

async def start_scheduler(bot):
    """
    Запускает фоновые задачи с автоматическим перезапуском и возвращает список задач.
    Каждая задача выполняется в цикле с заданным интервалом (внутри самой функции).
    """
    # Интервалы между выполнениями (в секундах)
    INTERVAL_CHECK_EXPIRED = 3600
    INTERVAL_REMINDERS = 3600
    INTERVAL_REFRESH_SERVERS = 1800

    # Оборачиваем каждую функцию в бесконечный цикл с перезапуском и добавляем задержку между итерациями
    async def run_check_expired():
        while True:
            try:
                await check_expired_subscriptions(bot)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"check_expired_subscriptions failed: {e}", exc_info=True)
                await send_admin_alert(f"check_expired_subscriptions failed: {e}")
            await asyncio.sleep(INTERVAL_CHECK_EXPIRED)

    async def run_reminders():
        while True:
            try:
                await send_expiry_reminders(bot)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"send_expiry_reminders failed: {e}", exc_info=True)
                await send_admin_alert(f"send_expiry_reminders failed: {e}")
            await asyncio.sleep(INTERVAL_REMINDERS)

    async def run_refresh_servers():
        while True:
            try:
                await refresh_server_pool_periodically()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"refresh_server_pool_periodically failed: {e}", exc_info=True)
                await send_admin_alert(f"refresh_server_pool_periodically failed: {e}")
            await asyncio.sleep(INTERVAL_REFRESH_SERVERS)

    # Создаём и возвращаем задачи (обёрнутые в run_with_restart для защиты от падений)
    tasks = [
        asyncio.create_task(run_with_restart(run_check_expired, "check_expired")),
        asyncio.create_task(run_with_restart(run_reminders, "reminders")),
        asyncio.create_task(run_with_restart(run_refresh_servers, "refresh_servers")),
    ]
    logger.info("Фоновые задачи запущены с автоматическим перезапуском")
    return tasks