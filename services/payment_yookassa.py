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
from db.crud import is_bot_payment_processed, log_bot_payment

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

            payment_data = {
                "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
                "confirmation": {"type": "redirect", "return_url": return_url},
                "capture": True,
                "description": description,
                "metadata": metadata
            }

            # Уникальный idempotence_key для каждого запроса
            unique_suffix = f"{uuid.uuid4().hex}_{int(time.time() * 1000)}"
            idempotence_key = hashlib.sha256(unique_suffix.encode()).hexdigest()[:50]

            payment = await asyncio.to_thread(Payment.create, payment_data, idempotence_key)

            # Если платёж уже успешен (маловероятно из-за уникального ключа), но на всякий случай
            if payment.status == "succeeded":
                logger.info(f"Payment {payment.id} already succeeded (should not happen with new key)")
                # Всё равно возвращаем ссылку? Нет, ссылки уже нет. Лучше сообщить об ошибке.
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

    async def process_webhook(self, webhook_data: Dict[str, Any], bot) -> bool:
        event = webhook_data.get("event")
        if event != "payment.succeeded":
            logger.info(f"Ignored event: {event}")
            return True

        payment_obj = webhook_data.get("object", {})
        payment_id = payment_obj.get("id")
        if not payment_id:
            logger.warning("Webhook without payment_id")
            return False

        if await is_bot_payment_processed(payment_id):
            logger.info(f"Payment {payment_id} already processed")
            return True

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

        # Вызываем внутреннее API для активации
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    f"http://{settings.INTERNAL_API_HOST}:{settings.INTERNAL_API_PORT}/activate",
                    json={
                        "telegram_id": int(telegram_id),
                        "product_type": product_type,
                        "period": period,
                        "payment_id": payment_id
                    },
                    headers={"Authorization": f"Bearer {settings.INTERNAL_API_SECRET}"},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("status") in ("ok", "already_activated"):
                            await log_bot_payment(payment_id, int(telegram_id))
                            if bot:
                                await bot.send_message(
                                    int(telegram_id),
                                    "✅ Оплата прошла успешно! Ваша подписка активирована."
                                )
                            logger.info(f"Activated for user {telegram_id}, payment {payment_id}")
                            return True
                    logger.error(f"Activation failed: HTTP {resp.status}")
                    return False
            except Exception as e:
                logger.error(f"Error calling internal API: {e}")
                return False


yookassa_service = YookassaService()