# services/payment_yookassa.py
import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import aiohttp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
from yookassa import Configuration, Payment
from yookassa.domain.exceptions import ApiError

from admin import send_admin_alert
from config import settings
from db.base import retry_db_operation
from db.crud import activate_subscription
from db.models import BotPayment, BotUser
from handlers.ui import Texts
from services.vpn_manager import get_vpn_manager

logger = logging.getLogger(__name__)


class YookassaService:
    def __init__(self):
        Configuration.account_id = settings.YOOKASSA_SHOP_ID
        Configuration.secret_key = settings.YOOKASSA_API_KEY
        logger.info("✅ YookassaService инициализирован")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(
            (ApiError, aiohttp.ClientError, asyncio.TimeoutError)
        ),
    )
    async def create_payment(
        self, amount: float, description: str, metadata: dict
    ) -> dict[str, Any] | None:
        logger.info(
            f"💳 Создание платежа: amount={amount}, description={description}, metadata={metadata}"
        )
        try:
            return_url = settings.YOOKASSA_RETURN_URL
            if not return_url:
                logger.error("❌ YOOKASSA_RETURN_URL не задан в .env")
                return None

            idempotency_key = str(uuid.uuid4())

            loop = asyncio.get_running_loop()
            payment = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: Payment.create(
                        {
                            "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
                            "confirmation": {
                                "type": "redirect",
                                "return_url": return_url,
                            },
                            "capture": True,
                            "description": description,
                            "metadata": metadata,
                        },
                        idempotency_key,
                    ),
                ),
                timeout=10.0,
            )

            logger.info(
                f"✅ Платёж создан: id={payment.id}, status={payment.status}, confirmation_url={payment.confirmation.confirmation_url}"
            )

            return {
                "payment_id": payment.id,
                "status": payment.status,
                "confirmation_url": payment.confirmation.confirmation_url,
                "amount": payment.amount.value,
            }

        except asyncio.TimeoutError:
            logger.error("❌ Таймаут при создании платежа в ЮKassa (10s)")
            return None
        except Exception:
            logger.error("❌ Ошибка создания платежа")
            return None

    @retry_db_operation(max_retries=3)
    async def process_webhook(
        self, webhook_data: dict, session: AsyncSession, bot
    ) -> bool:
        start_time = datetime.now(timezone.utc)

        # === Извлекаем только критичные поля ===
        obj = webhook_data.get("object", {})
        payment_id = obj.get("id")
        event = webhook_data.get("event")
        amount_value = obj.get("amount", {}).get("value")
        metadata = obj.get("metadata", {})

        logger.info(
            f"🔔 Webhook {payment_id}: event={event}, amount={amount_value} RUB"
        )

        if event != "payment.succeeded" or not payment_id:
            logger.info(f"⏭️ Webhook {payment_id}: ignored")
            return False

        # === 1. Проверка в БД ===
        stmt = select(BotPayment).where(BotPayment.payment_id == payment_id)
        db_payment = (await session.execute(stmt)).scalar_one_or_none()
        if not db_payment:
            logger.error(f"❌ Webhook {payment_id}: not found in DB")
            await send_admin_alert(f"⚠️ Платёж {payment_id} не найден в БД")
            return False

        if db_payment.is_paid:
            logger.info(f"ℹ️ Webhook {payment_id}: already processed")
            return True

        # === 2. Double-check через API ЮKassa (только статус и сумма) ===
        loop = asyncio.get_running_loop()
        try:
            verified = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: Payment.find_one(payment_id)),
                timeout=3.0,
            )
        except Exception as e:
            logger.error(f"❌ Webhook {payment_id}: double-check failed: {e}")
            if bot and db_payment:
                await bot.send_message(
                    db_payment.telegram_id,
                    "✅ Платёж получен, идёт проверка. Если через 10 минут ключ не придёт – напишите в поддержку.",
                )
            return False

        if verified.status != "succeeded":
            logger.warning(
                f"⚠️ Webhook {payment_id}: status mismatch (API={verified.status})"
            )
            return False

        # Сверяем сумму (обязательно)
        if abs(float(db_payment.amount) - float(verified.amount.value)) > 0.01:
            logger.critical(f"🚨 Webhook {payment_id}: amount mismatch!")
            await send_admin_alert(f"🚨 Несовпадение суммы для платежа {payment_id}")
            return False

        # === 3. Извлекаем метаданные (только то, что нужно) ===
        telegram_id = db_payment.telegram_id
        product_type = metadata.get("product_type")
        period = metadata.get("period")

        if not product_type or not period:
            logger.warning(f"⚠️ Webhook {payment_id}: missing metadata")
            await send_admin_alert(f"⚠️ Неполные метаданные в платеже {payment_id}")
            return False

        # Проверяем, что telegram_id в метаданных совпадает с БД (защита от подмены)
        if str(telegram_id) != metadata.get("telegram_id"):
            logger.error(f"❌ Webhook {payment_id}: telegram_id mismatch")
            await send_admin_alert("⚠️ Подозрительный платёж: ID не совпадает")
            return False

        # === 4. Обновляем статус платежа ===
        db_payment.status = "succeeded"
        db_payment.is_paid = True
        db_payment.updated_at = datetime.now(timezone.utc)
        session.add(db_payment)

        # === 5. Активируем подписку ===
        stmt_user = (
            select(BotUser)
            .where(BotUser.telegram_id == telegram_id)
            .with_for_update(skip_locked=True)
        )
        user = (await session.execute(stmt_user)).scalar_one_or_none()

        success = await activate_subscription(
            session, telegram_id, product_type, period, payment_id, user=user
        )
        if not success:
            logger.warning(f"⚠️ Webhook {payment_id}: activation failed")
            return False

        logger.info(
            f"✅ Webhook {payment_id}: subscription activated for {telegram_id}"
        )

        # === 6. Отправка сообщения и фоновое создание ключа (только для VPN) ===
        if product_type == "vpn" and bot:
            days = settings.PERIOD_DAYS.get(period, 0)
            msg = Texts.payment_success_with_date(user.vpn_subscription_end, days, None)
            await bot.send_message(telegram_id, msg, parse_mode="Markdown")

            # Фоновая задача
            async def create_key():
                try:
                    vpn_manager = get_vpn_manager()
                    if vpn_manager:
                        link = await vpn_manager.get_or_create_link(telegram_id)
                        if link:
                            await bot.send_message(
                                telegram_id,
                                f"🔗 Ваш ключ:\n`{link}`",
                                parse_mode="Markdown",
                            )
                            logger.info(f"✅ Webhook {payment_id}: key sent")
                except Exception as e:
                    logger.error(f"❌ Webhook {payment_id}: key creation error: {e}")
                    await send_admin_alert(
                        f"❌ Ошибка создания ключа для {telegram_id}: {e}"
                    )

            asyncio.create_task(create_key())

        # === 7. Итог ===
        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
        logger.info(f"✅ Webhook {payment_id}: done in {elapsed:.2f}s")
        return True


yookassa_service = YookassaService()
logger.info("✅ YookassaService готов к работе")
