# services/payment_yookassa.py
import hashlib
import asyncio
import logging
import aiohttp
import uuid
from typing import Optional, Dict, Any
from yookassa import Configuration, Payment
from yookassa.domain.exceptions import ApiError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from config import settings
from datetime import datetime, timezone
from db.crud import activate_subscription
from db.models import BotPayment, BotUser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiogram.exceptions import (
    TelegramForbiddenError,
    TelegramRetryAfter,
    TelegramNetworkError,
)
from aiohttp import ClientError

from handlers import get_vpn_manager
from admin import send_admin_alert
from db.base import retry_db_operation

logger = logging.getLogger(__name__)

class YookassaService:
    def __init__(self):
        Configuration.account_id = settings.YOOKASSA_SHOP_ID
        Configuration.secret_key = settings.YOOKASSA_API_KEY

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((ApiError, aiohttp.ClientError, asyncio.TimeoutError))
    )
    async def create_payment(
        self,
        amount: float,
        description: str,
        metadata: dict
    ) -> Optional[Dict[str, Any]]:
        try:
            return_url = settings.YOOKASSA_RETURN_URL
            if not return_url:
                logger.error("YOOKASSA_RETURN_URL не задан в .env")
                return None

            idempotency_key = str(uuid.uuid4())
            
            loop = asyncio.get_running_loop()
            payment = await loop.run_in_executor(
                None,
                lambda: Payment.create({
                    "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
                    "confirmation": {"type": "redirect", "return_url": return_url},
                    "capture": True,
                    "description": description,
                    "metadata": metadata
                }, idempotency_key)
            )
            
            logger.debug(f"Yookassa payment response: {payment}")
            
            return {
                "payment_id": payment.id,
                "status": payment.status,
                "confirmation_url": payment.confirmation.confirmation_url,
                "amount": payment.amount.value
            }

        except Exception as e:
            logger.error(f"Error creating Yookassa payment: {e}", exc_info=True)
            return None

    @retry_db_operation(max_retries=3)
    async def process_webhook(self, webhook_data: dict, session: AsyncSession, bot) -> bool:
        try:
            event = webhook_data.get("event")
            obj = webhook_data.get("object", {})
            payment_id = obj.get("id")

            if not payment_id or event != "payment.succeeded":
                logger.info(f"Webhook ignored: event={event}, payment_id={payment_id}")
                return False

            # Проверка дубликата
            stmt = select(BotPayment).where(BotPayment.payment_id == payment_id)
            result = await session.execute(stmt)
            db_payment = result.scalar_one_or_none()

            if not db_payment:
                logger.error(f"Payment {payment_id} not found in local Database.")
                return False

            if db_payment.status == "succeeded" or db_payment.is_paid:
                logger.info(f"Payment {payment_id} was already processed earlier.")
                return True

            # Double-Check через API ЮKassa с таймаутом 10 секунд
            loop = asyncio.get_running_loop()
            try:
                verified_payment = await asyncio.wait_for(
                    loop.run_in_executor(None, lambda: Payment.find_one(payment_id)),
                    timeout=10.0
                )
            except asyncio.TimeoutError:
                logger.error(f"Double-Check timed out for payment {payment_id}")
                await send_admin_alert(f"⏱️ Таймаут при проверке платежа {payment_id} через API ЮKassa")
                return False
            except Exception as api_err:
                logger.error(f"Double-Check failed. Can't find payment {payment_id} via API: {api_err}")
                await send_admin_alert(f"❌ Ошибка проверки платежа {payment_id} через API: {api_err}")
                return False

            if verified_payment.status != "succeeded":
                logger.warning(
                    f"Fraud attempt alert! Webhook said 'succeeded', but API status is "
                    f"'{verified_payment.status}' for payment {payment_id}"
                )
                return False

            expected_amount = float(db_payment.amount)
            actual_amount = float(verified_payment.amount.value)
            if abs(expected_amount - actual_amount) > 0.01 or verified_payment.amount.currency != "RUB":
                logger.critical(
                    f"Fraud Alert! Amount mismatch for payment {payment_id}. "
                    f"Expected: {expected_amount}, Got: {actual_amount}"
                )
                return False

            # Транзакция обновления
            async with session.begin():
                stmt_lock = select(BotPayment).where(BotPayment.payment_id == payment_id).with_for_update(skip_locked=True)
                result_lock = await session.execute(stmt_lock)
                db_payment = result_lock.scalar_one_or_none()

                if db_payment is None:
                    logger.info(f"Payment {payment_id} is locked by another transaction, skipping")
                    return True

                if db_payment.is_paid:
                    logger.info(f"Payment {payment_id} was already processed (double-check inside transaction).")
                    return True

                db_payment.status = "succeeded"
                db_payment.is_paid = True
                db_payment.updated_at = datetime.now(timezone.utc)
                session.add(db_payment)

                # Используем telegram_id из записи БД, а не из metadata (защита от подмены)
                telegram_id = db_payment.telegram_id
                metadata = verified_payment.metadata or {}
                product_type = metadata.get("product_type")
                period = metadata.get("period")

                # Проверяем, что метаданные соответствуют тому, что мы ожидаем
                if not (product_type and period):
                    logger.warning(f"Incomplete metadata in payment {payment_id}")
                    return False

                # Дополнительно проверяем, что telegram_id в metadata совпадает с сохранённым
                meta_tg = metadata.get("telegram_id")
                if meta_tg is not None and int(meta_tg) != telegram_id:
                    logger.error(f"Telegram ID mismatch in payment {payment_id}: db={telegram_id}, meta={meta_tg}")
                    await send_admin_alert(f"⚠️ Подозрительный платёж: ID в метаданных ({meta_tg}) не совпадает с БД ({telegram_id})")
                    return False

                stmt_user = select(BotUser).where(BotUser.telegram_id == telegram_id).with_for_update()
                user = (await session.execute(stmt_user)).scalar_one_or_none()

                success = await activate_subscription(
                    session, telegram_id, product_type, period, payment_id, user=user
                )

                if not success:
                    logger.warning(f"activate_subscription returned False for user {telegram_id}, payment {payment_id}")
                    return False

                logger.info(f"Successfully activated subscription for user {telegram_id} via secure webhook.")

            # Вне транзакции – создание ключа VPN
            if product_type == "vpn":
                try:
                    vpn_manager = get_vpn_manager()
                    if not vpn_manager:
                        logger.error("VPNManager not initialized, cannot create key")
                        raise RuntimeError("VPNManager is None")

                    link = await vpn_manager.get_or_create_link(telegram_id)

                    if link and bot:
                        try:
                            await bot.send_message(
                                telegram_id,
                                f"✅ VPN подписка активирована!\n\n"
                                f"🔗 Ваша ссылка для подключения:\n`{link}`\n\n"
                                f"Скопируйте ссылку и вставьте в VPN-приложение.",
                                parse_mode="Markdown"
                            )
                            logger.info(f"VPN link sent to user {telegram_id}")
                        except TelegramForbiddenError:
                            logger.info(f"User {telegram_id} blocked bot, cannot send link")
                        except TelegramRetryAfter as e:
                            logger.warning(f"Flood limit for {telegram_id}, waiting {e.retry_after}s")
                            await asyncio.sleep(e.retry_after)
                            try:
                                await bot.send_message(
                                    telegram_id,
                                    f"✅ VPN подписка активирована!\n\n"
                                    f"🔗 Ваша ссылка для подключения:\n`{link}`\n\n"
                                    f"Скопируйте ссылку и вставьте в VPN-приложение.",
                                    parse_mode="Markdown"
                                )
                            except Exception:
                                pass
                        except (TelegramNetworkError, ClientError) as e:
                            logger.warning(f"Network error sending link to {telegram_id}: {e}")
                        except Exception as e:
                            logger.exception(f"Unexpected error sending link to {telegram_id}")
                    else:
                        # Не удалось создать ключ или bot отсутствует
                        if bot:
                            try:
                                await bot.send_message(
                                    telegram_id,
                                    "✅ Ваша VPN-подписка активирована!\n\n"
                                    "🔑 Мы автоматически создаём ключ, это может занять несколько минут. "
                                    "Как только ключ будет готов, мы пришлём его вам.\n\n"
                                    "Если через 10 минут ничего не пришло – нажмите кнопку «🚀 Подключить VPN»."
                                )
                            except Exception as e:
                                logger.error(f"Failed to send waiting message to {telegram_id}: {e}")
                        await send_admin_alert(
                            f"⚠️ Не удалось сразу создать VPN-ключ для {telegram_id} после оплаты. "
                            f"Запланирована автоматическая повторная попытка в фоновой задаче."
                        )
                        logger.warning(f"Не удалось создать ключ для {telegram_id} сразу после оплаты")
                except asyncio.TimeoutError:
                    logger.error(f"Timeout while creating key for user {telegram_id}")
                    await send_admin_alert(f"⏱️ Таймаут при создании ключа для пользователя {telegram_id} после оплаты")
                    if bot:
                        try:
                            await bot.send_message(
                                telegram_id,
                                "✅ Ваша VPN-подписка активирована, но произошла задержка при создании ключа.\n"
                                "Мы автоматически повторим попытку в течение нескольких минут. "
                                "Если ключ не придёт, нажмите «🚀 Подключить VPN»."
                            )
                        except Exception:
                            pass
                except Exception as e:
                    logger.exception(f"Ошибка при создании ключа для {telegram_id} после оплаты: {e}")
                    await send_admin_alert(
                        f"❌ Критическая ошибка при создании ключа для {telegram_id} после оплаты: {e}"
                    )
                    if bot:
                        try:
                            await bot.send_message(
                                telegram_id,
                                "✅ Ваша VPN-подписка активирована, но произошла техническая ошибка при создании ключа.\n"
                                "Мы автоматически повторим попытку в течение нескольких минут. "
                                "Если ключ не придёт, нажмите «🚀 Подключить VPN»."
                            )
                        except Exception:
                            pass

            return True

        except Exception as e:
            logger.error(f"Critical error in process_webhook: {e}", exc_info=True)
            return False

yookassa_service = YookassaService()