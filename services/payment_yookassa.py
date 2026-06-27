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

from handlers import get_vpn_manager
from admin import send_admin_alert

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

        # ШАГ 1: Проверка, не обработан ли уже этот платёж (без блокировки)
        stmt = select(BotPayment).where(BotPayment.payment_id == payment_id)
        result = await session.execute(stmt)
        db_payment = result.scalar_one_or_none()

        if not db_payment:
            logger.error(f"Payment {payment_id} not found in local Database.")
            return False

        if db_payment.status == "succeeded" or db_payment.is_paid:
            logger.info(f"Payment {payment_id} was already processed earlier.")
            return True

        # ШАГ 2: Double-Check через API ЮKassa (вне транзакции)
        loop = asyncio.get_running_loop()
        try:
            verified_payment = await loop.run_in_executor(
                None,
                lambda: Payment.find_one(payment_id)
            )
        except Exception as api_err:
            logger.error(f"Double-Check failed. Can't find payment {payment_id} via API: {api_err}")
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

        # ШАГ 3: ОДНА ТРАНЗАКЦИЯ – обновление статуса + активация
        async with session.begin():
            stmt_lock = select(BotPayment).where(BotPayment.payment_id == payment_id).with_for_update()
            result_lock = await session.execute(stmt_lock)
            db_payment = result_lock.scalar_one_or_none()

            if db_payment.is_paid:
                logger.info(f"Payment {payment_id} was already processed (double-check inside transaction).")
                return True

            db_payment.status = "succeeded"
            db_payment.is_paid = True
            db_payment.updated_at = datetime.now(timezone.utc)
            session.add(db_payment)  # необязательно, т.к. объект уже в сессии

            metadata = verified_payment.metadata or {}
            telegram_id = metadata.get("telegram_id") or db_payment.telegram_id
            product_type = metadata.get("product_type")
            period = metadata.get("period")

            if not (telegram_id and product_type and period):
                logger.warning(f"Incomplete metadata in payment {payment_id}")
                return False

            success = await activate_subscription(
                session, int(telegram_id), product_type, period, payment_id
            )

            if not success:
                logger.warning(f"activate_subscription returned False for user {telegram_id}, payment {payment_id}")
                return False

            logger.info(f"Successfully activated subscription for user {telegram_id} via secure webhook.")

        # ШАГ 4: Создание VPN-ключа (после фиксации транзакции)
        if product_type == "vpn":
            try:
                days = settings.PERIOD_DAYS.get(period, 30)
                vpn_manager = get_vpn_manager()
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
                else:
                    # Ключ не создан – уведомляем пользователя и админа
                    error_msg = (
                        "✅ Ваша VPN-подписка активирована, но не удалось создать ключ автоматически.\n"
                        "Пожалуйста, через пару минут нажмите кнопку «🚀 Подключить VPN» — "
                        "ключ будет создан повторно.\n"
                        "Если проблема сохраняется, обратитесь в поддержку."
                    )
                    if bot:
                        await bot.send_message(telegram_id, error_msg)
                    else:
                        logger.error("Bot instance is None, cannot send error message to user")

                    alert_msg = (
                        f"⚠️ Не удалось создать VPN-ключ для пользователя {telegram_id} "
                        f"после успешной оплаты (payment {payment_id}). Пользователь уведомлён, требуется контроль."
                    )
                    await send_admin_alert(alert_msg)
                    logger.error(f"Failed to create VPN key for user {telegram_id} after payment {payment_id}")
            except Exception as e:
                logger.exception(f"Error creating VPN key for user {telegram_id}: {e}")
                await send_admin_alert(
                    f"❌ Критическая ошибка при создании ключа для {telegram_id} после оплаты: {e}"
                )
                if bot:
                    try:
                        await bot.send_message(
                            telegram_id,
                            "✅ Ваша VPN-подписка активирована, но произошла техническая ошибка.\n"
                            "Пожалуйста, нажмите «🚀 Подключить VPN» через минуту – ключ будет создан.\n"
                            "Приносим извинения за неудобства."
                        )
                    except Exception:
                        pass

        return True

    except Exception as e:
        logger.error(f"Critical error in process_webhook: {e}", exc_info=True)
        return False

yookassa_service = YookassaService()
