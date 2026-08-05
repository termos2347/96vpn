import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from aiogram.exceptions import (
    TelegramForbiddenError,
    TelegramRetryAfter,
    TelegramNetworkError,
)
from aiohttp import ClientError

from db.base import AsyncSessionLocal, retry_db_operation
from db.models import BotUser
from handlers import get_vpn_manager
from admin import send_admin_alert

logger = logging.getLogger(__name__)

async def run_with_restart(coro, task_name: str, restart_delay: int = 5):
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
            logger.warning(f"Task {task_name} finished unexpectedly, restarting in {restart_delay}s")
            await asyncio.sleep(restart_delay)

@retry_db_operation(max_retries=3)
async def check_expired_subscriptions(bot):
    """Отзывает ключи у пользователей с истекшей подпиской."""
    async with AsyncSessionLocal() as session:
        now = datetime.now(timezone.utc)
        stmt = select(BotUser).where(
            BotUser.vpn_subscription_end < now,
            BotUser.vpn_client_id.isnot(None)
        )
        result = await session.execute(stmt)
        expired_users = result.scalars().all()

    if not expired_users:
        logger.debug("Нет истёкших подписок для отзыва")
        return

    logger.info(f"Найдено {len(expired_users)} истёкших подписок для обработки")

    vpn_manager = get_vpn_manager()
    if not vpn_manager:
        logger.error("VPNManager не инициализирован, пропускаем отзыв ключей")
        return

    for user in expired_users:
        telegram_id = user.telegram_id
        client_uuid = user.vpn_client_id

        try:
            revoked = await vpn_manager.revoke_key(telegram_id)
            if revoked:
                logger.info(f"Key {client_uuid} revoked for user {telegram_id}")
                try:
                    await bot.send_message(
                        telegram_id,
                        "❌ Ваша подписка истекла. Для продления перейдите в раздел оплаты."
                    )
                except Exception as e:
                    logger.warning(f"Could not notify user {telegram_id}: {e}")
            else:
                logger.error(f"Failed to revoke key for user {telegram_id}")
                await send_admin_alert(f"Не удалось отозвать ключ {client_uuid} для user_id={telegram_id}")
        except Exception as e:
            logger.exception(f"Error revoking key for user {telegram_id}: {e}")

@retry_db_operation(max_retries=3)
async def send_expiry_reminders(bot):
    """Отправляет напоминания об истечении подписки."""
    async with AsyncSessionLocal() as session:
        now = datetime.now(timezone.utc)
        result = await session.execute(
            select(BotUser).where(
                BotUser.vpn_subscription_end > now,
                BotUser.vpn_client_id.isnot(None)
            )
        )
        users = result.scalars().all()

    if not users:
        logger.debug("Нет активных подписок для напоминаний")
        return

    today = now.date()
    for user in users:
        days_left = (user.vpn_subscription_end - now).days
        if days_left not in (7, 3, 1):
            continue

        if user.last_reminder_sent and user.last_reminder_sent.date() == today:
            continue

        day_word = {7: "7 дней", 3: "3 дня", 1: "1 день"}[days_left]
        message_sent = False

        for attempt in range(3):
            try:
                await bot.send_message(
                    user.telegram_id,
                    f"⏰ Ваша подписка истекает через {day_word}.\n"
                    f"Дата окончания: {user.vpn_subscription_end.strftime('%d.%m.%Y')}\n"
                    f"Продлите её в разделе 💳 Оплатить , чтобы не остаться без доступа."
                )
                message_sent = True
                break
            except TelegramForbiddenError:
                logger.info(f"User {user.telegram_id} blocked the bot, skipping reminders")
                break
            except TelegramRetryAfter as e:
                logger.warning(f"Flood limit for {user.telegram_id}, wait {e.retry_after}s")
                if attempt < 2:
                    await asyncio.sleep(e.retry_after)
                else:
                    break
            except (TelegramNetworkError, ClientError) as e:
                logger.warning(f"Network error sending reminder to {user.telegram_id}, attempt {attempt+1}: {e}")
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
            except Exception as e:
                logger.error(f"Unexpected error sending reminder to {user.telegram_id}: {e}")
                break

        if message_sent:
            # Обновляем last_reminder_sent внутри транзакции с блокировкой
            async with AsyncSessionLocal() as session_upd:
                async with session_upd.begin():
                    stmt_lock = select(BotUser).where(BotUser.id == user.id).with_for_update(skip_locked=True)
                    db_user = (await session_upd.execute(stmt_lock)).scalar_one_or_none()
                    if not db_user:
                        continue
                    if db_user.last_reminder_sent and db_user.last_reminder_sent.date() == today:
                        continue
                    db_user.last_reminder_sent = now
                    # commit автоматически при выходе из begin()
            logger.info(f"Отправлено напоминание за {days_left} дн. пользователю {user.telegram_id}")
        else:
            logger.error(f"Не удалось отправить напоминание пользователю {user.telegram_id} после 3 попыток")

@retry_db_operation(max_retries=3)
async def retry_missing_keys(bot):
    """Создаёт ключи для пользователей с активной подпиской, но без vpn_client_id."""
    async with AsyncSessionLocal() as session:
        now = datetime.now(timezone.utc)
        stmt = select(BotUser).where(
            BotUser.vpn_subscription_end > now,
            BotUser.vpn_client_id.is_(None)
        )
        result = await session.execute(stmt)
        users = result.scalars().all()

    if not users:
        logger.debug("Нет пользователей с активной подпиской и без ключа")
        return

    logger.info(f"Найдено {len(users)} пользователей с активной подпиской и без ключа")

    vpn_manager = get_vpn_manager()
    if not vpn_manager:
        logger.error("VPNManager не инициализирован, пропускаем создание ключей")
        return

    for user in users:
        async with AsyncSessionLocal() as sess:
            async with sess.begin():
                stmt_lock = select(BotUser).where(BotUser.id == user.id).with_for_update(skip_locked=True)
                db_user = (await sess.execute(stmt_lock)).scalar_one_or_none()
                if not db_user:
                    continue
                if db_user.vpn_client_id is not None:
                    continue
                if db_user.vpn_subscription_end <= now:
                    continue

                try:
                    link = await vpn_manager.get_or_create_link(db_user.telegram_id)
                    if link:
                        try:
                            await bot.send_message(
                                db_user.telegram_id,
                                f"🔗 Ваш ключ готов:\n`{link}`\n\nСкопируйте ссылку и вставьте в приложение.",
                                parse_mode="Markdown"
                            )
                            logger.info(f"Ключ успешно создан для {db_user.telegram_id} через фоновую задачу")
                        except Exception as e:
                            logger.warning(f"Could not send key to {db_user.telegram_id}: {e}")
                    else:
                        logger.warning(f"Не удалось создать ключ для {db_user.telegram_id} в фоновой задаче")
                except Exception as e:
                    logger.exception(f"Ошибка создания ключа для {db_user.telegram_id} в фоновой задаче: {e}")

async def start_scheduler(bot):
    INTERVAL_CHECK_EXPIRED = 3600   # 1 час
    INTERVAL_REMINDERS = 3600        # 1 час
    INTERVAL_RETRY_KEYS = 300        # 5 минут

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

    async def run_retry_keys():
        while True:
            try:
                await retry_missing_keys(bot)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"retry_missing_keys failed: {e}", exc_info=True)
                await send_admin_alert(f"retry_missing_keys failed: {e}")
            await asyncio.sleep(INTERVAL_RETRY_KEYS)

    tasks = [
        asyncio.create_task(run_with_restart(run_check_expired, "check_expired")),
        asyncio.create_task(run_with_restart(run_reminders, "reminders")),
        asyncio.create_task(run_with_restart(run_retry_keys, "retry_keys")),
    ]
    logger.info("Фоновые задачи запущены с автоматическим перезапуском")
    return tasks