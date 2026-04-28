import logging
from datetime import datetime
from typing import Optional, Dict, Any
from yookassa import Configuration, Payment
from sqlalchemy.orm import Session
from sqlalchemy import select
from db.models import User
from web.config import settings

logger = logging.getLogger(__name__)

class YookassaService:
    def __init__(self):
        Configuration.account_id = settings.YOOKASSA_SHOP_ID
        Configuration.secret_key = settings.YOOKASSA_API_KEY
    
    async def create_payment(
        self,
        user_id: int,
        amount: float,
        plan: str,
        db: Session,
        description: str = "Подписка на NeuroPrompt Premium"
    ) -> Optional[Dict[str, Any]]:
        """Создаёт платёж в Yookassa"""
        try:
            stmt = select(User).where(User.id == user_id)
            user = db.execute(stmt).scalars().first()
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
            
            payment = Payment.create(payment_data, idempotency_key=f"payment_{user_id}_{datetime.utcnow().timestamp()}")
            
            # Сохраняем payment_id в БД
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
        """Получает статус платежа"""
        try:
            payment = Payment.find_one(payment_id)
            return payment.status
        except Exception as e:
            logger.error(f"Error getting payment status: {e}")
            return None
    
    async def process_webhook(
        self,
        webhook_data: Dict[str, Any],
        db: Session
    ) -> bool:
        """Обрабатывает webhook от Yookassa"""
        try:
            if webhook_data.get("event") != "payment.succeeded":
                logger.info(f"Skipping webhook event: {webhook_data.get('event')}")
                return True
            
            payment = webhook_data.get("object", {})
            payment_id = payment.get("id")
            
            if not payment_id:
                logger.error("Payment ID not found in webhook")
                return False
            
            # Ищем пользователя по payment_id
            stmt = select(User).where(User.yookassa_payment_id == payment_id)
            user = db.execute(stmt).scalars().first()
            
            if not user:
                logger.warning(f"User not found for payment {payment_id}")
                return False
            
            # Извлекаем информацию о плане из метаданных
            metadata = payment.get("metadata", {})
            plan = metadata.get("plan", "monthly")
            
            # Определяем количество дней подписки
            days = 90 if plan == "quarterly" else 30
            
            # Активируем подписку
            from web.services.auth import SubscriptionService
            await SubscriptionService.renew_subscription(db, user, days)
            
            logger.info(f"Subscription activated for user {user.id} after payment {payment_id}")
            return True
        except Exception as e:
            logger.error(f"Error processing webhook: {e}")
            return False

yookassa_service = YookassaService()
