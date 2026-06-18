import hashlib
import asyncio
import logging
import aiohttp
import uuid
import time
from typing import Optional, Dict, Any
from yookassa import Configuration, Payment
from yookassa.domain.exceptions import ApiError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from config import settings
from db.crud import activate_subscription
from db.base import AsyncSessionLocal
from sqlalchemy.ext.asyncio import AsyncSession   # <-- добавлен импорт

logger = logging.getLogger(__name__)

class YookassaService:
    def __init__(self):
        Configuration.account_id = settings.YOOKASSA_SHOP_ID

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
        # ... (оставляем без изменений) ...
        try:
            return_url = settings.YOOKASSA_RETURN_URL
            if not return_url:
                logger.error("YOOKASSA_RETURN_URL не задан в .env")
                return None

            payment_data = {
                "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
                "confirmation": {"type": "redirect", "return_url": return_url},
                "capture": True,
                "description": description,
                "metadata": metadata
            }

            unique_suffix = f"{uuid.uuid4().hex}_{int(time.time() * 1000)}"
            idempotence_key = hashlib.sha256(unique_suffix.encode()).hexdigest()[:50]

            payment = await asyncio.to_thread(Payment.create, payment_data, idempotence_key)

            if payment.status == "succeeded":
                logger.info(f"Payment {payment.id} already succeeded (should not happen with new key)")
                return None

            if payment.confirmation is None:
                logger.error(f"Payment {payment.id} has no confirmation object. Status: {payment.status}")
                return None

            confirmation_url = getattr(payment.confirmation, 'confirmation_url', None)
            if not confirmation_url:
                logger.error(f"Payment {payment.id} confirmation has no URL")
                return None

            return {
                "payment_id": payment.id,
                "confirmation_url": confirmation_url,
                "status": payment.status
            }
        except Exception as e:
            logger.error(f"Error creating payment: {e}", exc_info=True)
            return None

    async def process_webhook(self, webhook_data: Dict[str, Any], session: AsyncSession, bot) -> bool:
        """
        Обрабатывает вебхук от ЮKassa.
        Использует атомарную функцию activate_subscription для гарантии идемпотентности.
        """
        event = webhook_data.get("event")
        if event != "payment.succeeded":
            logger.info(f"Ignored event: {event}")
            return True

        payment_obj = webhook_data.get("object", {})
        payment_id = payment_obj.get("id")
        if not payment_id:
            logger.warning("Webhook without payment_id")
            return False

        # Рекомендуется добавить проверку подписи вебхука (см. документацию ЮKassa)
        # Здесь можно реализовать проверку заголовка X-Yookassa-Signature

        metadata = payment_obj.get("metadata", {})
        source = metadata.get("source")
        if source != "bot":
            logger.warning(f"Webhook from unknown source: {source}")
            return False

        telegram_id = metadata.get("telegram_id")
        product_type = metadata.get("product_type")
        period = metadata.get("period")
        if not all([telegram_id, product_type, period]):
            logger.error(f"Incomplete metadata: {metadata}")
            return False

        # Атомарно активируем подписку в переданной сессии
        try:
            async with session.begin():
                success = await activate_subscription(
                    session,
                    int(telegram_id),
                    product_type,
                    period,
                    payment_id
                )
            if success:
                logger.info(f"Activated for user {telegram_id}, payment {payment_id}")
                if bot:
                    try:
                        await bot.send_message(
                            int(telegram_id),
                            "✅ Оплата прошла успешно! Ваша подписка активирована."
                        )
                    except Exception as e:
                        logger.error(f"Failed to send notification to {telegram_id}: {e}")
                return True
            else:
                logger.warning(f"Payment {payment_id} already processed, skipping")
                return True
        except Exception as e:
            logger.error(f"Error activating subscription: {e}", exc_info=True)
            return False

yookassa_service = YookassaService()