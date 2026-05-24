import hashlib
import asyncio
import logging
import aiohttp
from datetime import datetime, timezone
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

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def create_payment(self, amount: float, description: str, metadata: dict) -> Optional[Dict[str, Any]]:
        """Создаёт платёж в ЮKassa, возвращает payment_id и confirmation_url"""
        try:
            payment_data = {
                "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
                "confirmation": {"type": "redirect", "return_url": ""},
                "capture": True,
                "description": description,
                "metadata": metadata
            }
            # Идемпотентность на основе метаданных
            token = metadata.get("token", "")  # может быть пустым
            idempotence_key = hashlib.sha256(f"{metadata.get('telegram_id')}_{metadata.get('product_type')}_{metadata.get('period')}_{token}".encode()).hexdigest()[:50]
            
            payment = await asyncio.to_thread(Payment.create, payment_data, idempotence_key)
            return {
                "payment_id": payment.id,
                "confirmation_url": payment.confirmation.confirmation_url,
                "status": payment.status
            }
        except Exception as e:
            logger.error(f"Error creating payment: {e}", exc_info=True)
            return None

    async def process_webhook(self, webhook_data: Dict[str, Any], bot) -> bool:
        """Обрабатывает вебхук ЮKassa и активирует подписку через внутреннее API"""
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
                            # Уведомляем пользователя
                            await bot.send_message(int(telegram_id), "✅ Оплата прошла успешно! Ваша подписка активирована. Используйте /start для получения VPN-ссылки.")
                            logger.info(f"Activated for user {telegram_id}, payment {payment_id}")
                            return True
                    logger.error(f"Activation failed: HTTP {resp.status}")
                    return False
            except Exception as e:
                logger.error(f"Error calling internal API: {e}")
                return False

yookassa_service = YookassaService()