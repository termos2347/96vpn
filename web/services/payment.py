import logging
from datetime import datetime
from typing import Optional, Dict, Any
from yookassa import Configuration, Payment
from yookassa.domain.exceptions import ApiError
from sqlalchemy.orm import Session
from sqlalchemy import select
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import requests.exceptions

from db.models import User
from config import settings
from web.services.auth import SubscriptionService

logger = logging.getLogger(__name__)


class YookassaService:
    def __init__(self):
        Configuration.account_id = settings.YOOKASSA_SHOP_ID
        Configuration.secret_key = settings.YOOKASSA_API_KEY

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((ApiError, requests.exceptions.ConnectionError, requests.exceptions.Timeout))
    )
    async def create_payment(
        self,
        user_id: int,
        amount: float,
        plan: str,
        db: Session,
        description: str = "Подписка на NeuroPrompt Premium"
    ) -> Optional[Dict[str, Any]]:
        """Создаёт платёж в Yookassa с автоматическими повторными попытками при сетевых ошибках"""
        try:
            user = db.execute(select(User).where(User.id == user_id)).scalars().first()
            if not user:
                logger.error(f"User {user_id} not found")
                return None

            payment_data = {
                "amount": {
                    "value": f"{amount:.2f}",
                    "currency": "RUB"
                },
                "confirmation": {
                    "type": "redirect",
                    "return_url": settings.YOOKASSA_RETURN_URL
                },
                "capture": True,
                "description": f"{description} ({plan})",
                "metadata": {
                    "user_id": user_id,
                    "plan": plan,
                    "source": "web_app"
                }
            }

            if user.yookassa_customer_id:
                payment_data["customer_id"] = user.yookassa_customer_id
            if user.payment_method_id:
                payment_data["payment_method_id"] = user.payment_method_id

            # Idempotency key — уникальный для каждого запроса
            idempotence_key = f"payment_{user_id}_{datetime.utcnow().timestamp()}"
            payment = Payment.create(payment_data, idempotence_key)

            user.yookassa_payment_id = payment.id
            db.commit()

            logger.info(f"Payment created: {payment.id} for user {user_id}, amount: {amount}")
            return {
                "payment_id": payment.id,
                "status": payment.status,
                "confirmation_url": payment.confirmation.confirmation_url if hasattr(payment, 'confirmation') else None,
                "created_at": datetime.utcnow()
            }
        except Exception as e:
            logger.error(f"Error creating payment: {e}")
            return None

    async def get_payment_status(self, payment_id: str) -> Optional[str]:
        """Получает статус платежа из ЮKassa"""
        try:
            payment = Payment.find_one(payment_id)
            return payment.status
        except Exception as e:
            logger.error(f"Error getting payment status: {e}")
            return None

    async def process_webhook(self, webhook_data: Dict[str, Any], db: Session) -> bool:
        """Обрабатывает уведомление об успешном платеже и активирует подписку"""
        try:
            event = webhook_data.get("event")
            if event != "payment.succeeded":
                logger.info(f"Skipping webhook event: {event}")
                return True

            payment = webhook_data.get("object", {})
            payment_id = payment.get("id")
            if not payment_id:
                logger.error("Payment ID not found in webhook")
                return False

            # Поиск пользователя по payment_id
            user = db.execute(select(User).where(User.yookassa_payment_id == payment_id)).scalars().first()
            if not user:
                logger.warning(f"User not found for payment {payment_id}")
                return False

            metadata = payment.get("metadata", {})
            plan = metadata.get("plan", "monthly")
            days = 90 if plan == "quarterly" else 30

            # Проверяем, не активирована ли уже подписка с большим сроком
            if user.is_active and user.expiry_date and (user.expiry_date - datetime.utcnow()).days > days - 5:
                logger.info(f"User {user.id} already has active subscription, skipping renewal")
                return True

            # Активируем подписку
            await SubscriptionService.renew_subscription(db, user, days)
            logger.info(f"Subscription activated for user {user.id} after payment {payment_id}")
            return True
        except Exception as e:
            logger.error(f"Error processing webhook: {e}")
            return False


# Глобальный экземпляр сервиса
yookassa_service = YookassaService()