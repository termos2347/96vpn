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
from db.models import BotPayment  # Импортируем модель платежа для сверки
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

class YookassaService:
    def __init__(self):
        Configuration.account_id = settings.YOOKASSA_SHOP_ID
        Configuration.secret_key = settings.YOOKASSA_API_KEY  # Маппим ваш API_KEY в поле secret_key для SDK

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
            
            # Интеграция с официальным SDK ЮKassa синхронная, запускаем в энтити-потоке во избежание блокировок event loop
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

    async def process_webhook(self, webhook_data: dict, session: AsyncSession, bot) -> bool:
        """Безопасная обработка входящего вебхука с Double-Check валидацией через API ЮKassa."""
        try:
            event = webhook_data.get("event")
            obj = webhook_data.get("object", {})
            payment_id = obj.get("id")

            if not payment_id or event != "payment.succeeded":
                logger.info(f"Webhook ignored: event={event}, payment_id={payment_id}")
                return False

            # Double-Check
            loop = asyncio.get_running_loop()
            try:
                verified_payment = await loop.run_in_executor(
                    None,
                    lambda: Payment.find_one(payment_id)   # <--- ИСПРАВЛЕНО find → find_one
                )
            except Exception as api_err:
                logger.error(f"Double-Check failed. Can't find payment {payment_id} via API: {api_err}")
                return False

            if verified_payment.status != "succeeded":
                logger.warning(f"Fraud attempt alert! Webhook said 'succeeded', but API status is '{verified_payment.status}' for payment {payment_id}")
                return False

            # Блокировка строки БД (FOR UPDATE)
            async with session.begin_nested():
                stmt = select(BotPayment).where(BotPayment.payment_id == payment_id).with_for_update()
                result = await session.execute(stmt)
                db_payment = result.scalar_one_or_none()

                if not db_payment:
                    logger.error(f"Payment {payment_id} not found in local Database.")
                    return False

                if db_payment.status == "succeeded" or db_payment.is_paid:
                    logger.info(f"Payment {payment_id} was already processed earlier.")
                    return True

                # Валидация суммы
                expected_amount = float(db_payment.amount)
                actual_amount = float(verified_payment.amount.value)
                if abs(expected_amount - actual_amount) > 0.01 or verified_payment.amount.currency != "RUB":
                    logger.critical(f"Fraud Alert! Amount mismatch for payment {payment_id}. Expected: {expected_amount}, Got: {actual_amount}")
                    return False

                db_payment.status = "succeeded"
                db_payment.is_paid = True
                db_payment.updated_at = datetime.now(timezone.utc)
                session.add(db_payment)

            # Активация подписки
            metadata = verified_payment.metadata or {}
            telegram_id = metadata.get("telegram_id") or db_payment.telegram_id
            product_type = metadata.get("product_type")
            period = metadata.get("period")

            if telegram_id and product_type and period:
                success = await activate_subscription(session, int(telegram_id), product_type, period, payment_id)
                if success:
                    await session.commit()
                    logger.info(f"Successfully activated subscription for user {telegram_id} via secure webhook.")

                    # ----- СОЗДАНИЕ КЛЮЧА И ОТПРАВКА ССЫЛКИ -----
                    if product_type == "vpn":
                        from handlers import get_vpn_manager
                        from config import VPN_PRICES  # или свои PERIOD_DAYS
                        # Определяем дни из периода
                        period_days = {"1m": 30, "3m": 90, "6m": 180}
                        days = period_days.get(period, 30)
                        vpn_manager = get_vpn_manager()
                        if vpn_manager:
                            try:
                                link = await vpn_manager.create_key(int(telegram_id), days)
                                if link and bot:
                                    await bot.send_message(
                                        telegram_id,
                                        f"✅ VPN подписка активирована на {days} дней!\n\n"
                                        f"🔗 Ваша ссылка для подключения:\n`{link}`\n\n"
                                        f"Скопируйте ссылку и вставьте в VPN-приложение.",
                                        parse_mode="Markdown"
                                    )
                                    logger.info(f"VPN link sent to user {telegram_id}")
                                elif link:
                                    logger.warning(f"Bot instance is None, cannot send link to user {telegram_id}")
                                else:
                                    logger.error(f"Failed to create VPN key for user {telegram_id} after payment {payment_id}")
                                    # Можно отправить администратору уведомление
                            except Exception as e:
                                logger.exception(f"Error creating VPN key for user {telegram_id}: {e}")
                        else:
                            logger.error("VPNManager not available, cannot create key")
                    # Если bypass – аналогичная логика
                    return True
                else:
                    logger.warning(f"activate_subscription returned False for user {telegram_id}, payment {payment_id}")
                    return False
            else:
                logger.warning(f"Incomplete metadata in payment {payment_id}")
                return False

        except Exception as e:
            await session.rollback()
            logger.error(f"Critical error in process_webhook: {e}", exc_info=True)
            return False

yookassa_service = YookassaService()
