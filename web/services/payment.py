import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from yookassa import Configuration, Payment
from yookassa.domain.exceptions import ApiError
from sqlalchemy.orm import Session
from sqlalchemy import select
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import requests.exceptions
import jwt
import aiohttp

from db.models import WebUser
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
        user_id: Optional[int],
        amount: float,
        plan: str,
        db: Session,
        description: str = "Подписка на NeuroPrompt Premium",
        metadata: dict = None
    ) -> Optional[Dict[str, Any]]:
        try:
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
                "metadata": metadata or {}
            }

            if user_id is not None:
                user = db.execute(select(WebUser).where(WebUser.id == user_id)).scalars().first()
                if not user:
                    logger.error(f"User {user_id} not found")
                    return None
                if user.yookassa_customer_id:
                    payment_data["customer_id"] = user.yookassa_customer_id
                if user.payment_method_id:
                    payment_data["payment_method_id"] = user.payment_method_id
                payment_data["metadata"]["source"] = "web"
                payment_data["metadata"]["user_id"] = user_id

            idempotence_key = f"payment_{user_id or 'bot'}_{datetime.now(timezone.utc).timestamp()}"
            payment = Payment.create(payment_data, idempotence_key)

            if user_id:
                user = db.execute(select(WebUser).where(WebUser.id == user_id)).scalars().first()
                if user:
                    user.yookassa_payment_id = payment.id
                    db.commit()

            logger.info(f"Payment created: {payment.id}, amount: {amount}")
            return {
                "payment_id": payment.id,
                "status": payment.status,
                "confirmation_url": payment.confirmation.confirmation_url if hasattr(payment, 'confirmation') else None,
                "created_at": datetime.now(timezone.utc)
            }
        except Exception as e:
            logger.error(f"Error creating payment: {e}")
            return None

    async def get_payment_status(self, payment_id: str) -> Optional[str]:
        try:
            payment = Payment.find_one(payment_id)
            return payment.status
        except Exception as e:
            logger.error(f"Error getting payment status: {e}")
            return None

    async def process_webhook(self, webhook_data: Dict[str, Any], db: Session) -> bool:
        try:
            event = webhook_data.get("event")
            if event != "payment.succeeded":
                logger.info(f"Skipping webhook event: {event}")
                return True

            payment = webhook_data.get("object", {})
            metadata = payment.get("metadata", {})
            source = metadata.get("source")
            payment_id = payment.get("id")

            if source == "bot":
                return await self._activate_bot_subscription(metadata, payment_id)

            if not payment_id:
                logger.error("Payment ID not found in webhook")
                return False

            user = db.execute(select(WebUser).where(WebUser.yookassa_payment_id == payment_id)).scalars().first()
            if not user:
                logger.warning(f"User not found for payment {payment_id}")
                return False

            plan = metadata.get("plan", "monthly")
            days = 90 if "quarterly" in plan else 30
            if "semiannual" in plan:
                days = 180

            if user.is_active and user.expiry_date and (user.expiry_date - datetime.now(timezone.utc)).days > days - 5:
                logger.info(f"User {user.id} already has active subscription, skipping renewal")
                return True

            await SubscriptionService.renew_subscription(db, user, days)
            logger.info(f"Subscription activated for user {user.id} after payment {payment_id}")
            return True
        except Exception as e:
            logger.error(f"Error processing webhook: {e}")
            return False

    async def _activate_bot_subscription(self, metadata: dict, payment_id: str) -> bool:
        try:
            token = metadata.get("token")
            if not token:
                logger.error("No token in webhook metadata")
                return False

            payload = jwt.decode(token, settings.INTERNAL_API_SECRET, algorithms=["HS256"], leeway=60)
            telegram_id = payload["telegram_id"]
            product_type = payload["product_type"]
            period = payload["period"]
        except Exception as e:
            logger.error(f"Token decode failed: {e}")
            return False

        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    "http://localhost:8001/activate",
                    json={
                        "telegram_id": telegram_id,
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
                            logger.info(f"Bot activation succeeded for {telegram_id}")
                            return True
                        else:
                            logger.error(f"Bot activation returned unexpected status: {data}")
                            return False
                    else:
                        logger.error(f"Bot activation returned {resp.status}")
                        return False
            except Exception as e:
                logger.error(f"Failed to call bot activation API: {e}")
                return False

    async def check_and_activate(self, payment_id: str, db: Session) -> bool:
        try:
            payment = Payment.find_one(payment_id)
            if payment.status == 'succeeded':
                metadata = payment.metadata
                if metadata and metadata.get('source') == 'bot':
                    return await self._activate_bot_subscription(metadata, payment_id)
                # Для веб-платежей просто считаем успехом
                return True
            return False
        except Exception as e:
            logger.error(f"Check and activate error: {e}")
            return False

yookassa_service = YookassaService()