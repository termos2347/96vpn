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
    retry_count = 3  # количество попыток отзыва ключа при ошибках сети

    while True:  # бесконечный цикл – задача не должна останавливаться
        try:
            async with AsyncSessionLocal() as session:
                now = datetime.now(timezone.utc)

                # Находим всех пользователей, у которых подписка истекла, но ключ ещё есть
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

                        # Пытаемся отозвать ключ с повторными попытками
                        for attempt in range(retry_count):
                            try:
                                success = await vpn_manager.revoke_key(user.telegram_id)
                                if success:
                                    break
                            except Exception as e:
                                # Сетевые ошибки или ошибки соединения с панелью
                                logger.warning(
                                    f"Ошибка при отзыве ключа {client_uuid} для user_id={user.telegram_id}, "
                                    f"попытка {attempt+1}/{retry_count}: {e}"
                                )
                                if attempt < retry_count - 1:
                                    await asyncio.sleep(2 ** attempt)  # экспоненциальная задержка
                            # Другие ошибки (не связанные с сетью) – прерываем попытки
                            except Exception as e:
                                logger.error(
                                    f"Неожиданная ошибка при отзыве ключа {client_uuid}, попытка {attempt+1}: {e}"
                                )
                                break

                        if success:
                            # revoke_key уже обнулил client_id и server_id внутри, но для надёжности делаем это явно
                            user.vpn_client_id = None
                            user.server_id = None
                            await session.commit()
                            logger.info(f"Ключ {client_uuid} отозван для user_id={user.telegram_id}")

                            # Уведомляем пользователя в Telegram
                            try:
                                await bot.send_message(
                                    user.telegram_id,
                                    "❌ Ваша VPN-подписка истекла. Для продления перейдите в раздел оплаты."
                                )
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

            # Пауза до следующей проверки (1 час)
            await asyncio.sleep(3600)

        except asyncio.CancelledError:
            # Задача отменяется – корректно завершаем работу
            logger.info("Task check_expired_subscriptions cancelled")
            raise  # пробрасываем, чтобы задача завершилась

        except Exception as e:
            # Любая другая критическая ошибка (например, потеря соединения с БД)
            logger.error(f"Критическая ошибка в задаче проверки подписок: {e}", exc_info=True)
            await send_admin_alert(f"Критическая ошибка в задаче проверки подписок: {e}")

            # Ждём минуту перед повторной попыткой, чтобы не зациклиться на временной проблеме
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