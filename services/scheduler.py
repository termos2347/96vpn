import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

# Добавляем недостающие исключения aiogram и aiohttp
from aiogram.exceptions import (
    TelegramForbiddenError,
    TelegramRetryAfter,
    TelegramNetworkError,
)
from aiohttp import ClientError

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
            logger.warning(f"Task {task_name} finished unexpectedly, restarting in {restart_delay}s")
            await asyncio.sleep(restart_delay)


@retry_db_operation(max_retries=3)
async def check_expired_subscriptions(bot):
    """
    Проверяет истёкшие VPN-подписки и отзывает ключи.
    Каждый пользователь обрабатывается в отдельной короткой транзакции с skip_locked.
    """
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

    retry_count = 3
    now = datetime.now(timezone.utc)

    for user in expired_users:
        telegram_id = user.telegram_id
        client_uuid = user.vpn_client_id
        server_id = user.server_id

        revoked_on_panel = False

        if not server_id:
            logger.warning(f"User {telegram_id} has no server_id, skipping panel revoke, will clean DB")
            revoked_on_panel = True
        else:
            for attempt in range(retry_count):
                try:
                    provider = await vpn_manager.pool.get_provider(server_id)
                    if not provider:
                        logger.error(f"Provider for server {server_id} not found, cannot revoke for user {telegram_id}")
                        break

                    revoked = await provider.revoke_client(client_uuid)
                    if revoked:
                        logger.info(f"Key {client_uuid} revoked on panel for user {telegram_id}")
                        revoked_on_panel = True
                        break
                    else:
                        client_info = await provider.get_client_by_uuid(client_uuid)
                        if client_info is None:
                            logger.info(f"Client {client_uuid} not found on panel, assuming already revoked")
                            revoked_on_panel = True
                            break
                        else:
                            logger.warning(f"revoke_client returned False but client exists, attempt {attempt+1}")
                except Exception as e:
                    logger.warning(f"Error revoking key {client_uuid} for user {telegram_id}, attempt {attempt+1}: {e}")
                    if attempt < retry_count - 1:
                        await asyncio.sleep(2 ** attempt)

        if not revoked_on_panel:
            logger.error(f"Не удалось отозвать ключ {client_uuid} для user_id={telegram_id} после {retry_count} попыток")
            await send_admin_alert(
                f"Не удалось отозвать ключ {client_uuid} для user_id={telegram_id} на панели"
            )
            continue

        async with AsyncSessionLocal() as session_upd:
            async with session_upd.begin():
                stmt_lock = select(BotUser).where(BotUser.id == user.id).with_for_update(skip_locked=True)
                db_user = (await session_upd.execute(stmt_lock)).scalar_one_or_none()
                if not db_user:
                    logger.warning(f"User {telegram_id} already locked or deleted, skipping")
                    continue

                if db_user.vpn_subscription_end >= now:
                    logger.info(f"User {telegram_id} subscription was extended, skipping")
                    continue

                db_user.vpn_client_id = None
                db_user.server_id = None
                db_user.vpn_subscription_end = now - timedelta(days=1)

        logger.info(f"Key {client_uuid} revoked for user {telegram_id} (DB updated)")

        # --- ОТПРАВКА УВЕДОМЛЕНИЯ с полной обработкой ошибок ---
        try:
            await bot.send_message(
                telegram_id,
                "❌ Ваша VPN-подписка истекла. Для продления перейдите в раздел оплаты."
            )
        except TelegramForbiddenError:
            logger.info(f"User {telegram_id} blocked the bot, skipping notification")
        except TelegramRetryAfter as e:
            logger.warning(f"Flood limit for {telegram_id}, waiting {e.retry_after}s")
            await asyncio.sleep(e.retry_after)
            # Повторяем один раз
            try:
                await bot.send_message(
                    telegram_id,
                    "❌ Ваша VPN-подписка истекла. Для продления перейдите в раздел оплаты."
                )
            except Exception:
                pass
        except (TelegramNetworkError, ClientError) as e:
            logger.warning(f"Network error notifying {telegram_id}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error notifying {telegram_id}: {e}")


@retry_db_operation(max_retries=3)
async def send_expiry_reminders(bot):
    """Отправляет напоминания о скором истечении подписки (один проход)."""
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

        # Отправка с повторными попытками (до 3 раз)
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
            async with AsyncSessionLocal() as session_upd:
                async with session_upd.begin():
                    stmt_lock = select(BotUser).where(BotUser.id == user.id).with_for_update(skip_locked=True)
                    db_user = (await session_upd.execute(stmt_lock)).scalar_one_or_none()
                    if not db_user:
                        logger.warning(f"User {user.telegram_id} already locked or deleted, skipping")
                        continue
                    if db_user.last_reminder_sent and db_user.last_reminder_sent.date() == today:
                        logger.info(f"Reminder for {user.telegram_id} already sent today, skipping")
                        continue
                    db_user.last_reminder_sent = now

            logger.info(f"Отправлено напоминание за {days_left} дн. пользователю {user.telegram_id}")
        else:
            logger.error(f"Не удалось отправить напоминание пользователю {user.telegram_id} после 3 попыток")


@retry_db_operation(max_retries=3)
async def refresh_server_pool_periodically():
    """Обновляет пул серверов из БД (один проход, вызывается по расписанию)."""
    try:
        logger.info("🔄 Scheduled server pool refresh started")
        pool = get_server_pool()
        if not pool:
            logger.error("ServerPool not initialized, cannot refresh")
            return
        await pool.refresh_servers(wait_for_login=True, login_timeout=10.0)
        logger.info("✅ Server pool refreshed successfully")
    except Exception as e:
        logger.exception(f"Ошибка при обновлении пула серверов: {e}")
        raise


@retry_db_operation(max_retries=3)
async def retry_missing_keys(bot):
    """
    Периодически пытается создать VPN-ключи для пользователей,
    у которых подписка активна, но ключ отсутствует.
    """
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
                    logger.debug(f"Пользователь {user.telegram_id} уже заблокирован или удалён, пропускаем")
                    continue

                if db_user.vpn_client_id is not None:
                    logger.debug(f"У пользователя {user.telegram_id} уже есть ключ, пропускаем")
                    continue

                if db_user.vpn_subscription_end <= now:
                    logger.debug(f"Подписка пользователя {user.telegram_id} истекла, пропускаем")
                    continue

                try:
                    link = await vpn_manager.get_or_create_link(db_user.telegram_id)
                    if link:
                        # --- ОТПРАВКА КЛЮЧА с полной обработкой ошибок ---
                        try:
                            await bot.send_message(
                                db_user.telegram_id,
                                f"🔗 Ваш VPN-ключ готов:\n`{link}`\n\nСкопируйте ссылку и вставьте в приложение.",
                                parse_mode="Markdown"
                            )
                            logger.info(f"Ключ успешно создан для {db_user.telegram_id} через фоновую задачу")
                        except TelegramForbiddenError:
                            logger.info(f"User {db_user.telegram_id} blocked the bot, skipping key send")
                        except TelegramRetryAfter as e:
                            logger.warning(f"Flood limit for {db_user.telegram_id}, waiting {e.retry_after}s")
                            await asyncio.sleep(e.retry_after)
                            # Повторяем один раз
                            try:
                                await bot.send_message(
                                    db_user.telegram_id,
                                    f"🔗 Ваш VPN-ключ готов:\n`{link}`\n\nСкопируйте ссылку и вставьте в приложение.",
                                    parse_mode="Markdown"
                                )
                                logger.info(f"Ключ успешно отправлен после задержки для {db_user.telegram_id}")
                            except Exception:
                                pass
                        except (TelegramNetworkError, ClientError) as e:
                            logger.warning(f"Network error sending key to {db_user.telegram_id}: {e}")
                        except Exception as e:
                            logger.error(f"Unexpected error sending key to {db_user.telegram_id}: {e}")
                    else:
                        logger.warning(f"Не удалось создать ключ для {db_user.telegram_id} в фоновой задаче")
                except Exception as e:
                    logger.exception(f"Ошибка создания ключа для {db_user.telegram_id} в фоновой задаче: {e}")


async def start_scheduler(bot):
    """
    Запускает фоновые задачи с автоматическим перезапуском и возвращает список задач.
    """
    INTERVAL_CHECK_EXPIRED = 3600   # 1 час
    INTERVAL_REMINDERS = 3600        # 1 час
    INTERVAL_REFRESH_SERVERS = 1800  # 30 минут
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
        asyncio.create_task(run_with_restart(run_refresh_servers, "refresh_servers")),
        asyncio.create_task(run_with_restart(run_retry_keys, "retry_keys")),
    ]
    logger.info("Фоновые задачи запущены с автоматическим перезапуском")
    return tasks