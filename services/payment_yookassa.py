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
from services.vpn_manager import get_vpn_manager

# ВАЖНО: НЕ импортируем handlers.ui на уровне модуля —
# это вызывает циклический импорт (см. комментарий в шапке admin/bot.py).
# Тексты импортируются лениво внутри process_webhook().

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
            f"💳 Создание платежа: amount={amount}, "
            f"description={description}, metadata={metadata}"
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

            confirmation_url = (
                payment.confirmation.confirmation_url
                if payment.confirmation
                else None
            )
            if not confirmation_url:
                logger.error("❌ ЮKassa не вернула confirmation_url")
                return None

            amount_value = (
                payment.amount.value if payment.amount else f"{amount:.2f}"
            )

            logger.info(
                f"✅ Платёж создан: id={payment.id}, status={payment.status}, "
                f"confirmation_url={confirmation_url}"
            )

            return {
                "payment_id": payment.id,
                "status": payment.status,
                "confirmation_url": confirmation_url,
                "amount": amount_value,
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
        # ЛЕНИВЫЙ ИМПОРТ — обходит циклический импорт:
        # handlers/__init__.py → handlers/payment.py → payment_yookassa.py
        from handlers.ui import Texts

        start_time = datetime.now(timezone.utc)

        obj = webhook_data.get("object", {})
        payment_id = obj.get("id")
        event = webhook_data.get("event")
        amount_value = obj.get("amount", {}).get("value")
        metadata = obj.get("metadata", {}) or {}

        logger.info(
            f"🔔 Webhook {payment_id}: event={event}, amount={amount_value} RUB"
        )

        if not payment_id:
            logger.warning("⏭️ Webhook: no payment_id (malformed payload)")
            return False

        if event != "payment.succeeded":
            # Возвращаем True, чтобы aiohttp-хендлер отдал 200.
            # Иначе ЮKassa будет ретраить canceled/refunded вечно.
            logger.info(f"⏭️ Webhook {payment_id}: event={event} acknowledged")
            return True

        # === 1. Проверка в БД с блокировкой строки ===
        stmt = (
            select(BotPayment)
            .where(BotPayment.payment_id == payment_id)
            .with_for_update()
        )
        db_payment = (await session.execute(stmt)).scalar_one_or_none()
        if not db_payment:
            logger.error(f"❌ Webhook {payment_id}: not found in DB")
            await send_admin_alert(f"⚠️ Платёж {payment_id} не найден в БД")
            return False

        if db_payment.is_paid:
            logger.info(f"ℹ️ Webhook {payment_id}: already processed")
            return True

        # === 2. Double-check через API ЮKassa ===
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
                    "✅ Платёж получен, идёт проверка. Если через 10 минут ключ "
                    "не придёт – напишите в поддержку.",
                )
            return False

        if verified.status != "succeeded":
            logger.warning(
                f"⚠️ Webhook {payment_id}: status mismatch (API={verified.status})"
            )
            return False

        if verified.amount is None or verified.amount.value is None:
            logger.error(f"❌ Webhook {payment_id}: API не вернул сумму")
            await send_admin_alert(
                f"⚠️ ЮKassa не вернула сумму по платежу {payment_id}"
            )
            return False

        if abs(float(db_payment.amount) - float(verified.amount.value)) > 0.01:
            logger.critical(f"🚨 Webhook {payment_id}: amount mismatch!")
            await send_admin_alert(f"🚨 Несовпадение суммы для платежа {payment_id}")
            return False

        # === 3. Метаданные ===
        # webhook может не содержать metadata (или содержать подделку) —
        # берём объединение, отдавая приоритет ответу API (verified).
        verified_metadata = getattr(verified, "metadata", None) or {}
        combined_metadata = {**metadata, **verified_metadata}

        telegram_id = db_payment.telegram_id
        product_type = combined_metadata.get("product_type")
        period = combined_metadata.get("period")
        metadata_telegram_id = combined_metadata.get("telegram_id")

        if not product_type or not period:
            logger.warning(
                f"⚠️ Webhook {payment_id}: missing metadata "
                f"(webhook={metadata}, verified={verified_metadata})"
            )
            await send_admin_alert(f"⚠️ Неполные метаданные в платеже {payment_id}")
            return False

        # telegram_id в metadata может прийти как str или int — сравниваем строки
        if str(telegram_id) != str(metadata_telegram_id):
            logger.error(
                f"❌ Webhook {payment_id}: telegram_id mismatch "
                f"(db={telegram_id}, metadata={metadata_telegram_id})"
            )
            await send_admin_alert("⚠️ Подозрительный платёж: ID не совпадает")
            return False

        # === 4. Продление подписки ===
        # ВАЖНО: activate_subscription сам пометит BotPayment.is_paid=True
        # (внутри одной транзакции, после успешной активации).
        # Здесь НЕ ставим is_paid заранее — иначе при неудаче активации
        # платёж останется помеченным оплаченным, а подписка — нет.
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

        if user is None:
            stmt_user = select(BotUser).where(BotUser.telegram_id == telegram_id)
            user = (await session.execute(stmt_user)).scalar_one_or_none()

        logger.info(
            f"✅ Webhook {payment_id}: subscription activated for {telegram_id}"
        )

        # === 5. Сообщение + фоновое создание ключа ===
        if product_type == "vpn" and bot:
            days = settings.PERIOD_DAYS.get(period, 0)
            vpn_end = user.vpn_subscription_end if user else None
            msg = Texts.payment_success_with_date(vpn_end, days, None)
            await bot.send_message(telegram_id, msg, parse_mode="Markdown")

            async def _create_key_task():
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

            asyncio.create_task(_create_key_task())

        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
        logger.info(f"✅ Webhook {payment_id}: done in {elapsed:.2f}s")
        return True


yookassa_service = YookassaService()
logger.info("✅ YookassaService готов к работе")