import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from yookassa import Configuration, Payment
from yookassa.domain.exceptions import ApiError
from sqlalchemy.ext.asyncio import AsyncSession
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
        db: AsyncSession,
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
                result = await db.execute(select(WebUser).where(WebUser.id == user_id))
                user = result.scalars().first()
                if not user:
                    logger.error(f"User {user_id} not found")
                    return None
                if user.yookassa_customer_id:
                    payment_data["customer_id"] = user.yookassa_customer_id
                if user.payment_method_id:
                    payment_data["payment_method_id"] = user.payment_method_id
                payment_data["metadata"]["source"] = "web"
                payment_data["metadata"]["user_id"] = user_id
                payment_data["metadata"]["plan"] = plan

            idempotence_key = f"payment_{user_id or 'bot'}_{datetime.now(timezone.utc).timestamp()}"
            payment = Payment.create(payment_data, idempotence_key)

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

    async def process_webhook(self, webhook_data: Dict[str, Any], db: AsyncSession) -> bool:
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

            if source == "web":
                user_id = metadata.get("user_id")
                if not user_id:
                    logger.error("Missing user_id in webhook")
                    return False
                try:
                    user_id = int(user_id)
                except (ValueError, TypeError):
                    logger.error(f"Invalid user_id: {user_id}")
                    return False

                result = await db.execute(select(WebUser).where(WebUser.id == user_id))
                user = result.scalars().first()
                if not user:
                    logger.warning(f"User {user_id} not found for payment {payment_id}")
                    return False

                # Защита от повторной обработки (но теперь yookassa_payment_id сохранится только после успеха)
                if user.yookassa_payment_id == payment_id:
                    logger.info(f"Payment {payment_id} already processed, skipping webhook")
                    return True

                plan = metadata.get("plan", "monthly")
                days = 30
                if plan == "quarterly":
                    days = 90
                elif plan == "semiannual":
                    days = 180

                await SubscriptionService.renew_subscription(db, user, days)
                user.yookassa_payment_id = payment_id
                await db.commit()
                logger.info(f"Subscription activated via webhook for user {user.id} (+{days} days)")
                return True

            return False
        except Exception as e:
            logger.error(f"Error processing webhook: {e}", exc_info=True)
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

    async def check_and_activate(self, payment_id: str, db: AsyncSession) -> bool:
        try:
            payment = Payment.find_one(payment_id)
            if payment.status != 'succeeded':
                logger.info(f"Payment {payment_id} not succeeded")
                return False

            metadata = payment.metadata
            if not metadata:
                logger.warning(f"No metadata for payment {payment_id}")
                return False

            source = metadata.get("source")
            if source == "bot":
                return await self._activate_bot_subscription(metadata, payment_id)

            if source == "web":
                user_id = metadata.get("user_id")
                if not user_id:
                    return False
                try:
                    user_id = int(user_id)
                except (ValueError, TypeError):
                    return False

                result = await db.execute(select(WebUser).where(WebUser.id == user_id))
                user = result.scalars().first()
                if not user:
                    logger.warning(f"User not found for payment {payment_id}")
                    return False

                if user.yookassa_payment_id == payment_id:
                    logger.info(f"Payment {payment_id} already processed, skipping")
                    return True

                plan = metadata.get("plan", "monthly")
                days = 30
                if plan == "quarterly":
                    days = 90
                elif plan == "semiannual":
                    days = 180

                await SubscriptionService.renew_subscription(db, user, days)
                user.yookassa_payment_id = payment_id
                await db.commit()
                logger.info(f"Subscription activated via return_url for user {user.id} (+{days} days)")
                return True

            return False
        except Exception as e:
            logger.error(f"Check and activate error: {e}", exc_info=True)
            return False

yookassa_service = YookassaService()