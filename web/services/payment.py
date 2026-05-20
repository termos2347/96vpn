import hashlib
import asyncio
import logging
import jwt
import aiohttp
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from yookassa import Configuration, Payment
from yookassa.domain.exceptions import ApiError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import requests.exceptions

from db.models import WebUser
from db.crud import is_bot_payment_processed, log_bot_payment
from config import settings
from web.services.auth import SubscriptionService

logger = logging.getLogger(__name__)


class YookassaService:
    def __init__(self):
        Configuration.account_id = settings.YOOKASSA_SHOP_ID
        Configuration.secret_key = settings.YOOKASSA_API_KEY

    # ---------------------- Создание платежа ----------------------
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
                "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
                "confirmation": {"type": "redirect", "return_url": settings.YOOKASSA_RETURN_URL},
                "capture": True,
                "description": f"{description} ({plan})",
                "metadata": metadata or {}
            }

            # ---- Идемпотентность: короткий ключ (хеш токена) ----
            if metadata and metadata.get("source") == "bot" and metadata.get("token"):
                token_hash = hashlib.sha256(metadata['token'].encode()).hexdigest()[:50]
                idempotence_key = f"vpn_{token_hash}"
            else:
                idempotence_key = f"payment_{user_id or 'bot'}_{datetime.now(timezone.utc).timestamp()}"

            logger.info(f"Creating payment, idempotence_key length: {len(idempotence_key)}")

            # ---- Данные веб-пользователя ----
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

            # ---- Создание платежа ----
            payment = await asyncio.to_thread(Payment.create, payment_data, idempotence_key)

            logger.info(f"✅ Payment created: {payment.id}, amount={amount}, plan={plan}")
            return {
                "payment_id": payment.id,
                "status": payment.status,
                "confirmation_url": payment.confirmation.confirmation_url if hasattr(payment, 'confirmation') else None,
                "created_at": datetime.now(timezone.utc)
            }
        except Exception as e:
            logger.error(f"Error creating payment: {e}", exc_info=True)
            return None

    async def get_payment_status(self, payment_id: str) -> Optional[str]:
        try:
            payment = await asyncio.to_thread(Payment.find_one, payment_id)
            return payment.status
        except Exception as e:
            logger.error(f"Error getting payment status: {e}")
            return None

    # ---------------------- Обработка вебхука ----------------------
    async def process_webhook(self, webhook_data: Dict[str, Any], db: AsyncSession) -> bool:
        try:
            event = webhook_data.get("event")
            if event != "payment.succeeded":
                logger.info(f"Skipping webhook event: {event}")
                return True

            payment = webhook_data.get("object", {})
            payment_id = payment.get("id")
            if not payment_id:
                logger.warning("Webhook without payment_id")
                return False

            # ---- Идемпотентность для ВСЕХ платежей ----
            if await is_bot_payment_processed(payment_id):
                logger.info(f"Payment {payment_id} already processed, skipping webhook")
                return True

            metadata = payment.get("metadata", {})
            source = metadata.get("source")
            logger.info(f"📨 Webhook processing: payment_id={payment_id}, source={source}")

            if source == "bot":
                success = await self._activate_bot_subscription(metadata, payment_id)
                if success:
                    telegram_id = metadata.get("telegram_id")
                    if telegram_id:
                        await log_bot_payment(payment_id, telegram_id)
                return success

            if source == "web":
                user_id = metadata.get("user_id")
                if not user_id:
                    logger.error("Missing user_id in web payment metadata")
                    return False
                user_id = int(user_id)

                result = await db.execute(select(WebUser).where(WebUser.id == user_id))
                user = result.scalars().first()
                if not user:
                    logger.warning(f"User {user_id} not found for payment {payment_id}")
                    return False
                if user.yookassa_payment_id == payment_id:
                    logger.info(f"Payment {payment_id} already attached to user {user_id}")
                    return True

                plan = metadata.get("plan", "monthly")
                days = 30 if plan == "monthly" else 90 if plan == "quarterly" else 180

                await SubscriptionService.renew_subscription(db, user, days)
                user.yookassa_payment_id = payment_id
                await db.commit()
                await log_bot_payment(payment_id, user_id)

                logger.info(f"✅ Subscription activated via webhook for user {user.id} (+{days} days)")
                return True

            logger.warning(f"Unknown source '{source}' in payment {payment_id}")
            return False

        except Exception as e:
            logger.error(f"Error processing webhook: {e}", exc_info=True)
            return False

    # ---------------------- Активация подписки бота (вызов internal API) ----------------------
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError))
    )
    async def _activate_bot_subscription(self, metadata: dict, payment_id: str) -> bool:
        if await is_bot_payment_processed(payment_id):
            logger.info(f"Bot payment {payment_id} already processed, skipping activation")
            return True

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
                    f"{settings.INTERNAL_API_URL}/activate",
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
                            logger.info(f"✅ Bot activation succeeded for {telegram_id}, payment {payment_id}")
                            return True
                        else:
                            logger.error(f"Bot activation returned unexpected status: {data}")
                            return False
                    else:
                        logger.error(f"Bot activation returned HTTP {resp.status}")
                        return False
            except Exception as e:
                logger.error(f"Failed to call bot activation API: {e}")
                return False

    # ---------------------- Синхронная проверка платежа (check-payment) ----------------------
    async def check_and_activate(self, payment_id: str, db: AsyncSession) -> bool:
        if await is_bot_payment_processed(payment_id):
            logger.info(f"Payment {payment_id} already processed, skipping check_and_activate")
            return True

        try:
            payment = await asyncio.to_thread(Payment.find_one, payment_id)
            if payment.status != 'succeeded':
                logger.info(f"Payment {payment_id} not succeeded, status={payment.status}")
                return False

            metadata = payment.metadata
            if not metadata:
                logger.warning(f"No metadata in payment {payment_id}")
                return False

            source = metadata.get("source")
            if source == "bot":
                success = await self._activate_bot_subscription(metadata, payment_id)
                if success:
                    telegram_id = metadata.get("telegram_id")
                    if telegram_id:
                        await log_bot_payment(payment_id, telegram_id)
                return success

            if source == "web":
                user_id = metadata.get("user_id")
                if not user_id:
                    logger.error("Missing user_id in web payment metadata")
                    return False
                user_id = int(user_id)

                result = await db.execute(select(WebUser).where(WebUser.id == user_id))
                user = result.scalars().first()
                if not user or user.yookassa_payment_id == payment_id:
                    return True

                plan = metadata.get("plan", "monthly")
                days = 30 if plan == "monthly" else 90 if plan == "quarterly" else 180
                await SubscriptionService.renew_subscription(db, user, days)
                user.yookassa_payment_id = payment_id
                await db.commit()
                await log_bot_payment(payment_id, user_id)
                logger.info(f"✅ Subscription activated via check_and_activate for user {user.id} (+{days} days)")
                return True

            return False
        except Exception as e:
            logger.error(f"Check and activate error: {e}", exc_info=True)
            return False


yookassa_service = YookassaService()