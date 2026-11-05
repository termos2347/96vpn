# services/scheduler.py
import asyncio
import logging
from datetime import datetime, timezone

from aiogram.exceptions import (
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)
from aiohttp import ClientError
from sqlalchemy import select

from admin import send_admin_alert
from db.base import AsyncSessionLocal, retry_db_operation
from db.models import BotUser
from services.vpn_manager import get_vpn_manager

logger = logging.getLogger(__name__)

# Окно, в течение которого повторное напоминание не отправляется.
# BUGFIX: раньше сравнивали `last_reminder_sent.date() == today` (UTC).
# Если шедулер прогонялся в 23:00 UTC и снова в 01:00 UTC — даты разные,
# и пользователь получал ВТОРОЕ напоминание через 2 часа. Окно 20 часов
# исключает такие дубли и не привязано к UTC-полуночи.
_REMINDER_COOLDOWN_SECONDS = 20 * 3600


@retry_db_operation(max_retries=3)
async def check_expired_subscriptions(bot):
    """Отзывает ключи у пользователей с истекшей подпиской.

    Защита от гонки: если между выборкой и отзывом подписку успели
    продлить (через /grant или оплату), revoke_key(require_expired=True)
    вернёт None и ключ НЕ будет отозван.
    """
    async with AsyncSessionLocal() as session:
        now = datetime.now(timezone.utc)
        stmt = select(BotUser.telegram_id).where(
            BotUser.vpn_subscription_end < now,
            BotUser.vpn_client_id.isnot(None),
        )
        result = await session.execute(stmt)
        telegram_ids = result.scalars().all()

    if not telegram_ids:
        logger.debug("Нет истёкших подписок для отзыва")
        return

    logger.info(
        f"Найдено {len(telegram_ids)} истёкших подписок для обработки"
    )

    vpn_manager = get_vpn_manager()
    if not vpn_manager:
        logger.error("VPNManager не инициализирован, пропускаем отзыв ключей")
        return

    for telegram_id in telegram_ids:
        try:
            revoked = await vpn_manager.revoke_key(
                telegram_id, require_expired=True
            )
        except Exception as e:
            logger.exception(
                f"Error revoking key for user {telegram_id}: {e}"
            )
            continue

        if revoked is None:
            logger.info(
                f"User {telegram_id} subscription renewed, skipping revoke"
            )
            continue

        if revoked:
            logger.info(f"Key revoked for user {telegram_id}")
            try:
                await bot.send_message(
                    telegram_id,
                    "❌ Ваша подписка истекла. "
                    "Для продления перейдите в раздел оплаты.",
                )
            except Exception as e:
                logger.warning(f"Could not notify user {telegram_id}: {e}")
        else:
            logger.error(f"Failed to revoke key for user {telegram_id}")
            await send_admin_alert(
                f"Не удалось отозвать ключ для user_id={telegram_id}"
            )


@retry_db_operation(max_retries=3)
async def send_expiry_reminders(bot):
    """Отправляет напоминания об истечении подписки."""
    async with AsyncSessionLocal() as session:
        now = datetime.now(timezone.utc)
        result = await session.execute(
            select(BotUser).where(
                BotUser.vpn_subscription_end > now, BotUser.vpn_client_id.isnot(None)
            )
        )
        users = result.scalars().all()

    if not users:
        logger.debug("Нет активных подписок для напоминаний")
        return

    for user in users:
        vpn_end = user.vpn_subscription_end
        if vpn_end is None:
            continue

        # BUGFIX: timedelta.days — floor, поэтому напоминание "за 7 дней"
        # могло не отправиться (если осталось 6д 23ч → days=6).
        # Округление делает окно [6.5, 7.5) → 7, [2.5, 3.5) → 3, [0.5, 1.5) → 1.
        days_left = round((vpn_end - now).total_seconds() / 86400)
        if days_left not in (7, 3, 1):
            continue

        # BUGFIX: окно 20 часов вместо сравнения UTC-дат.
        if user.last_reminder_sent:
            delta = (now - user.last_reminder_sent).total_seconds()
            if delta < _REMINDER_COOLDOWN_SECONDS:
                continue

        day_word = {7: "7 дней", 3: "3 дня", 1: "1 день"}[days_left]
        message_sent = False

        for attempt in range(3):
            try:
                await bot.send_message(
                    user.telegram_id,
                    f"⏰ Ваша подписка истекает через {day_word}.\n"
                    f"Дата окончания: "
                    f"{vpn_end.strftime('%d.%m.%Y')}\n"
                    f"Продлите её в разделе 💳 Оплатить , "
                    f"чтобы не остаться без доступа.",
                )
                message_sent = True
                break
            except TelegramForbiddenError:
                logger.info(
                    f"User {user.telegram_id} blocked the bot, skipping reminders"
                )
                break
            except TelegramRetryAfter as e:
                logger.warning(
                    f"Flood limit for {user.telegram_id}, wait {e.retry_after}s"
                )
                if attempt < 2:
                    await asyncio.sleep(e.retry_after)
                else:
                    break
            except (TelegramNetworkError, ClientError) as e:
                logger.warning(
                    f"Network error sending reminder to {user.telegram_id}, "
                    f"attempt {attempt + 1}: {e}"
                )
                if attempt < 2:
                    await asyncio.sleep(2**attempt)
            except Exception as e:
                logger.error(
                    f"Unexpected error sending reminder to {user.telegram_id}: {e}"
                )
                break

        if message_sent:
            async with AsyncSessionLocal() as session_upd:
                async with session_upd.begin():
                    stmt_lock = (
                        select(BotUser)
                        .where(BotUser.id == user.id)
                        .with_for_update(skip_locked=True)
                    )
                    db_user = (
                        await session_upd.execute(stmt_lock)
                    ).scalar_one_or_none()
                    if not db_user:
                        continue
                    # Повторная проверка окна под блокировкой —
                    # на случай параллельного прогона.
                    if db_user.last_reminder_sent:
                        delta = (
                            now - db_user.last_reminder_sent
                        ).total_seconds()
                        if delta < _REMINDER_COOLDOWN_SECONDS:
                            continue
                    db_user.last_reminder_sent = now
            logger.info(
                f"Отправлено напоминание за {days_left} дн. "
                f"пользователю {user.telegram_id}"
            )
        else:
            logger.error(
                f"Не удалось отправить напоминание пользователю "
                f"{user.telegram_id} после 3 попыток"
            )


@retry_db_operation(max_retries=3)
async def retry_missing_keys(bot):
    """Создаёт ключи для пользователей с активной подпиской, но без vpn_client_id.

    Блокировка строки БД НЕ удерживается во время сетевых вызовов.
    """
    async with AsyncSessionLocal() as session:
        now = datetime.now(timezone.utc)
        stmt = select(BotUser).where(
            BotUser.vpn_subscription_end > now, BotUser.vpn_client_id.is_(None)
        )
        result = await session.execute(stmt)
        users = result.scalars().all()

    if not users:
        logger.debug("Нет пользователей с активной подпиской и без ключа")
        return

    logger.info(
        f"Найдено {len(users)} пользователей с активной подпиской и без ключа"
    )

    vpn_manager = get_vpn_manager()
    if not vpn_manager:
        logger.error("VPNManager не инициализирован, пропускаем создание ключей")
        return

    for user in users:
        async with AsyncSessionLocal() as sess:
            db_user = await sess.get(BotUser, user.id)
            if db_user is None:
                continue
            db_end = db_user.vpn_subscription_end
            if db_end is None or db_end <= now:
                continue
            if db_user.vpn_client_id is not None:
                continue
            telegram_id = db_user.telegram_id

        try:
            link = await vpn_manager.get_or_create_link(telegram_id)
            if link:
                try:
                    await bot.send_message(
                        telegram_id,
                        f"🔗 Ваш ключ готов:\n`{link}`\n\n"
                        f"Скопируйте ссылку и вставьте в приложение.",
                        parse_mode="Markdown",
                    )
                    logger.info(
                        f"Ключ успешно создан для {telegram_id} "
                        f"через фоновую задачу"
                    )
                except Exception as e:
                    logger.warning(f"Could not send key to {telegram_id}: {e}")
            else:
                logger.warning(
                    f"Не удалось создать ключ для {telegram_id} "
                    f"в фоновой задаче"
                )
        except Exception as e:
            logger.exception(
                f"Ошибка создания ключа для {telegram_id} "
                f"в фоновой задаче: {e}"
            )


async def start_scheduler(bot):
    INTERVAL_CHECK_EXPIRED = 3600
    INTERVAL_REMINDERS = 3600
    INTERVAL_RETRY_KEYS = 300

    async def run_check_expired():
        while True:
            try:
                await check_expired_subscriptions(bot)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("check_expired_subscriptions failed")
                await send_admin_alert(f"check_expired_subscriptions failed: {e}")
            await asyncio.sleep(INTERVAL_CHECK_EXPIRED)

    async def run_reminders():
        while True:
            try:
                await send_expiry_reminders(bot)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("send_expiry_reminders failed")
                await send_admin_alert(f"send_expiry_reminders failed: {e}")
            await asyncio.sleep(INTERVAL_REMINDERS)

    async def run_retry_keys():
        while True:
            try:
                await retry_missing_keys(bot)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("retry_missing_keys failed")
                await send_admin_alert(f"retry_missing_keys failed: {e}")
            await asyncio.sleep(INTERVAL_RETRY_KEYS)

    tasks = [
        asyncio.create_task(run_check_expired(), name="check_expired"),
        asyncio.create_task(run_reminders(), name="reminders"),
        asyncio.create_task(run_retry_keys(), name="retry_keys"),
    ]
    logger.info("Фоновые задачи запущены")
    return tasks