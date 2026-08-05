# services/payment_yookassa.py
import hashlib
import asyncio
import logging
import aiohttp
import uuid
from typing import Optional, Dict, Any
from yookassa import Configuration, Payment
from yookassa.domain.exceptions import ApiError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from config import settings
from datetime import datetime, timezone
from db.crud import activate_subscription
from db.models import BotPayment, BotUser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiogram.exceptions import (
    TelegramForbiddenError,
    TelegramRetryAfter,
    TelegramNetworkError,
)
from aiohttp import ClientError

from services.vpn_manager import get_vpn_manager
from admin import send_admin_alert
from db.base import retry_db_operation
from handlers.ui import Texts

logger = logging.getLogger(__name__)


class YookassaService:
    def __init__(self):
        Configuration.account_id = settings.YOOKASSA_SHOP_ID
        Configuration.secret_key = settings.YOOKASSA_API_KEY
        logger.info("✅ YookassaService инициализирован")

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
        logger.info(f"💳 Создание платежа: amount={amount}, description={description}, metadata={metadata}")
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
                    lambda: Payment.create({
                        "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
                        "confirmation": {"type": "redirect", "return_url": return_url},
                        "capture": True,
                        "description": description,
                        "metadata": metadata
                    }, idempotency_key)
                ),
                timeout=10.0
            )
            
            logger.info(f"✅ Платёж создан: id={payment.id}, status={payment.status}, confirmation_url={payment.confirmation.confirmation_url}")
            
            return {
                "payment_id": payment.id,
                "status": payment.status,
                "confirmation_url": payment.confirmation.confirmation_url,
                "amount": payment.amount.value
            }

        except asyncio.TimeoutError:
            logger.error("❌ Таймаут при создании платежа в ЮKassa (10s)")
            return None
        except Exception as e:
            logger.error(f"❌ Ошибка создания платежа: {e}", exc_info=True)
            return None

    @retry_db_operation(max_retries=3)
    async def process_webhook(self, webhook_data: dict, session: AsyncSession, bot) -> bool:
        start_time = datetime.now(timezone.utc)
        logger.info(f"🕒 [START] Начало обработки вебхука в {start_time}")
        logger.info(f"📨 Получены данные вебхука: {webhook_data}")

        try:
            event = webhook_data.get("event")
            obj = webhook_data.get("object", {})
            payment_id = obj.get("id")
            logger.info(f"🔔 Событие: {event}, payment_id: {payment_id}")

            if not payment_id or event != "payment.succeeded":
                logger.info(f"⏭️ Вебхук проигнорирован: event={event}, payment_id={payment_id}")
                return False

            # ---------- Шаг 1: Проверка дубликата в БД ----------
            t0 = datetime.now(timezone.utc)
            logger.info(f"🔍 Шаг 1: Проверка платежа {payment_id} в БД...")
            stmt = select(BotPayment).where(BotPayment.payment_id == payment_id)
            result = await session.execute(stmt)
            db_payment = result.scalar_one_or_none()
            logger.info(f"⏱️ [1] Проверка БД заняла {(datetime.now(timezone.utc) - t0).total_seconds():.2f}s, найдено: {db_payment is not None}")

            if not db_payment:
                logger.error(f"❌ Платёж {payment_id} не найден в локальной БД.")
                await send_admin_alert(f"⚠️ Платёж {payment_id} не найден в БД при вебхуке")
                return False

            if db_payment.status == "succeeded" or db_payment.is_paid:
                logger.info(f"ℹ️ Платёж {payment_id} уже был обработан ранее.")
                return True

            # ---------- Шаг 2: Double-Check через API ЮKassa ----------
            t1 = datetime.now(timezone.utc)
            logger.info(f"🔍 Шаг 2: Double-check через API ЮKassa для платежа {payment_id}...")
            loop = asyncio.get_running_loop()
            try:
                verified_payment = await asyncio.wait_for(
                    loop.run_in_executor(None, lambda: Payment.find_one(payment_id)),
                    timeout=3.0
                )
                logger.info(f"⏱️ [2] Double-check API занял {(datetime.now(timezone.utc) - t1).total_seconds():.2f}s")
                logger.info(f"📊 Статус платежа из API: {verified_payment.status}")
            except asyncio.TimeoutError:
                logger.error(f"❌ Таймаут double-check для платежа {payment_id}")
                await send_admin_alert(f"⏱️ Таймаут при проверке платежа {payment_id} через API ЮKassa")
                if bot and db_payment:
                    try:
                        await bot.send_message(
                            db_payment.telegram_id,
                            "✅ Платёж получен, но идёт проверка. Если в течение 10 минут не придёт ключ, обратитесь в поддержку."
                        )
                    except Exception as e:
                        logger.error(f"Не удалось отправить сообщение пользователю: {e}")
                return False
            except Exception as api_err:
                logger.error(f"❌ Ошибка double-check: {api_err}", exc_info=True)
                await send_admin_alert(f"❌ Ошибка проверки платежа {payment_id} через API: {api_err}")
                return False

            if verified_payment.status != "succeeded":
                logger.warning(f"⚠️ Подозрение на мошенничество! Webhook сказал 'succeeded', а API вернул '{verified_payment.status}'")
                return False

            expected_amount = float(db_payment.amount)
            actual_amount = float(verified_payment.amount.value)
            logger.info(f"💰 Сравнение сумм: ожидалось {expected_amount}, получено {actual_amount}")
            if abs(expected_amount - actual_amount) > 0.01 or verified_payment.amount.currency != "RUB":
                logger.critical(f"🚨 ОБНАРУЖЕНО НЕСОВПАДЕНИЕ СУММЫ для платежа {payment_id}!")
                await send_admin_alert(f"🚨 Попытка мошенничества: несовпадение суммы для платежа {payment_id}")
                return False

            # ---------- Шаг 3: Обновление статуса платежа ----------
            t2 = datetime.now(timezone.utc)
            logger.info(f"🔍 Шаг 3: Обновление статуса платежа {payment_id} в БД...")
            db_payment.status = "succeeded"
            db_payment.is_paid = True
            db_payment.updated_at = datetime.now(timezone.utc)
            session.add(db_payment)
            logger.info(f"⏱️ [3] Обновление статуса заняло {(datetime.now(timezone.utc) - t2).total_seconds():.2f}s")

            # ---------- Шаг 4: Активация подписки ----------
            telegram_id = db_payment.telegram_id
            metadata = verified_payment.metadata or {}
            product_type = metadata.get("product_type")
            period = metadata.get("period")
            logger.info(f"🔍 Шаг 4: Активация подписки для пользователя {telegram_id}, продукт: {product_type}, период: {period}")

            if not (product_type and period):
                logger.warning(f"⚠️ Неполные метаданные в платеже {payment_id}: {metadata}")
                await send_admin_alert(f"⚠️ Неполные метаданные в платеже {payment_id}: {metadata}")
                return False

            meta_tg = metadata.get("telegram_id")
            if meta_tg is not None and int(meta_tg) != telegram_id:
                logger.error(f"❌ Несовпадение Telegram ID: в БД {telegram_id}, в метаданных {meta_tg}")
                await send_admin_alert(f"⚠️ Подозрительный платёж: ID в метаданных ({meta_tg}) не совпадает с БД ({telegram_id})")
                return False

            t3 = datetime.now(timezone.utc)
            stmt_user = select(BotUser).where(BotUser.telegram_id == telegram_id).with_for_update(skip_locked=True)
            user = (await session.execute(stmt_user)).scalar_one_or_none()
            logger.info(f"👤 Пользователь {telegram_id} найден: {user is not None}")

            success = await activate_subscription(
                session, telegram_id, product_type, period, payment_id, user=user
            )
            logger.info(f"⏱️ [4] activate_subscription заняла {(datetime.now(timezone.utc) - t3).total_seconds():.2f}s, результат: {success}")

            if not success:
                logger.warning(f"⚠️ activate_subscription вернула False для пользователя {telegram_id}, платеж {payment_id}")
                return False

            logger.info(f"✅ Подписка успешно активирована для пользователя {telegram_id} через вебхук.")

            # ---------- Шаг 5: Отправка сообщения пользователю ----------
            if product_type == "vpn":
                days = settings.PERIOD_DAYS.get(period, 0)
                new_vpn_end = user.vpn_subscription_end if user else None
                msg_text = Texts.payment_success_with_date(new_vpn_end, days, None)
                logger.info(f"📤 Шаг 5: Отправка сообщения об успехе пользователю {telegram_id}")

                t4 = datetime.now(timezone.utc)
                if bot:
                    try:
                        await bot.send_message(telegram_id, msg_text, parse_mode="Markdown")
                        logger.info(f"⏱️ [5] send_message заняла {(datetime.now(timezone.utc) - t4).total_seconds():.2f}s")
                        logger.info(f"✅ Сообщение об успешной оплате отправлено пользователю {telegram_id}")
                    except Exception as e:
                        logger.error(f"❌ Не удалось отправить сообщение пользователю {telegram_id}: {e}", exc_info=True)
                else:
                    logger.error("❌ bot не передан в process_webhook, сообщение не отправлено")

                # ---------- Шаг 6: Фоновое создание ключа ----------
                logger.info(f"🔑 Шаг 6: Запуск фонового создания ключа для пользователя {telegram_id}")
                async def create_key_background():
                    try:
                        logger.info(f"🔑 Фоновая задача: создание ключа для {telegram_id}...")
                        vpn_manager = get_vpn_manager()
                        if not vpn_manager:
                            logger.error(f"❌ VPNManager не инициализирован для пользователя {telegram_id}")
                            await send_admin_alert(f"❌ VPNManager не инициализирован для пользователя {telegram_id}")
                            return
                        link = await vpn_manager.get_or_create_link(telegram_id)
                        if link and bot:
                            try:
                                await bot.send_message(
                                    telegram_id,
                                    f"🔗 Ваш ключ готов:\n`{link}`\n\nСкопируйте и вставьте в приложение.",
                                    parse_mode="Markdown"
                                )
                                logger.info(f"✅ VPN-ключ отправлен пользователю {telegram_id} в фоне")
                            except Exception as e:
                                logger.error(f"❌ Не удалось отправить ключ пользователю {telegram_id}: {e}", exc_info=True)
                        else:
                            logger.warning(f"⚠️ Не удалось создать ключ для {telegram_id} в фоновой задаче (link={link})")
                            await send_admin_alert(f"⚠️ Не удалось создать ключ для {telegram_id} в фоне")
                    except Exception as e:
                        logger.exception(f"❌ Ошибка в фоновом создании ключа для {telegram_id}: {e}")
                        await send_admin_alert(f"❌ Ошибка создания ключа в фоне для {telegram_id}: {e}")

                asyncio.create_task(create_key_background())

            total_time = (datetime.now(timezone.utc) - start_time).total_seconds()
            logger.info(f"✅ Вебхук полностью обработан за {total_time:.2f}s")
            return True

        except Exception as e:
            logger.error(f"❌ Критическая ошибка в process_webhook: {e}", exc_info=True)
            await send_admin_alert(f"❌ Критическая ошибка в process_webhook: {e}")
            return False


yookassa_service = YookassaService()
logger.info("✅ YookassaService готов к работе")