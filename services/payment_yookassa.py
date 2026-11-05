# services/payment_yookassa.py
import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import aiohttp
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
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
from db.crud import activate_subscription
from db.models import BotPayment, BotUser
from services.vpn_manager import get_vpn_manager

# ВАЖНО: НЕ импортируем handlers.ui на уровне модуля —
# это вызывает циклический импорт. Тексты импортируются лениво
# внутри process_webhook().

logger = logging.getLogger(__name__)


class YookassaTransientError(Exception):
    """Транзиентная ошибка при обработке вебхука.

    Вызывающий код (internal_api.yookassa_webhook) должен вернуть 5xx,
    чтобы ЮKassa повторила вебхук. НЕ использовать для окончательных
    бизнес-ошибок (mismatch суммы, неполные метаданные) — те не должны
    триггерить ретраи.
    """


# --- Трекинг fire-and-forget задач ---
_pending_key_tasks: set[asyncio.Task] = set()


def _schedule_key_task(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _pending_key_tasks.add(task)
    task.add_done_callback(_pending_key_tasks.discard)
    return task


async def shutdown_pending_tasks(timeout: float = 5.0) -> None:
    """Отменяет все фоновые задачи создания ключей. Вызывается из
    run_all.on_shutdown()."""
    if not _pending_key_tasks:
        return
    logger.info(f"Cancelling {len(_pending_key_tasks)} pending YooKassa tasks")
    pending = list(_pending_key_tasks)
    for task in pending:
        if not task.done():
            task.cancel()
    try:
        await asyncio.wait_for(
            asyncio.gather(*pending, return_exceptions=True),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.warning("Some YooKassa tasks did not finish in time")
    _pending_key_tasks.clear()


def _log_create_payment_failure(retry_state) -> None:
    """BUGFIX: retry_error_callback вместо lambda _: None.

    Раньше причина окончательного провала (например, Invalid shop_id)
    полностью терялась — в логах были только warning'и внутри попыток.
    """
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    logger.error(
        f"❌ ЮKassa create_payment failed after "
        f"{retry_state.attempt_number} attempts: {exc}"
    )
    return None


class YookassaService:
    def __init__(self):
        Configuration.account_id = settings.YOOKASSA_SHOP_ID
        Configuration.secret_key = settings.YOOKASSA_API_KEY
        logger.info("✅ YookassaService инициализирован")

    async def create_payment(
        self, amount: float, description: str, metadata: dict
    ) -> dict[str, Any] | None:
        """Создаёт платёж в ЮKassa.

        BUGFIX: idempotency_key генерируется ОДИН раз до retry-обёртки.
        Раньше он создавался внутри retry-функции, поэтому каждая повторная
        попытка создавала новый платёж (при потере ответа после успешного
        создания — двойное списание и «висящий» pending).
        """
        idempotency_key = str(uuid.uuid4())
        return await self._create_payment_with_retry(
            amount, description, metadata, idempotency_key
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(
            (ApiError, aiohttp.ClientError, asyncio.TimeoutError)
        ),
        retry_error_callback=_log_create_payment_failure,
    )
    async def _create_payment_with_retry(
        self,
        amount: float,
        description: str,
        metadata: dict,
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        logger.info(
            f"💳 Создание платежа: amount={amount}, "
            f"description={description}, idempotency_key={idempotency_key}"
        )

        return_url = settings.YOOKASSA_RETURN_URL
        if not return_url:
            logger.error("❌ YOOKASSA_RETURN_URL не задан в .env")
            return None

        loop = asyncio.get_running_loop()

        try:
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
        except (ApiError, aiohttp.ClientError, asyncio.TimeoutError) as e:
            # retryable — пробрасываем наверх, Tenacity повторит
            logger.warning(
                f"⚠️ ЮKassa: ошибка создания платежа "
                f"({type(e).__name__}: {e}), повтор..."
            )
            raise
        except Exception:
            logger.exception("❌ Ошибка создания платежа")
            return None

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

    async def process_webhook(
        self, webhook_data: dict, session: AsyncSession, bot
    ) -> bool:
        """Обрабатывает вебхук ЮKassa.

        BUGFIX #1: снят @retry_db_operation — он переиспользовал ту же
        сессию после OperationalError, и повтор падал с
        PendingRollbackError. Ретраи теперь на уровне HTTP-обработчика
        (internal_api.yookassa_webhook), где на попытку создаётся
        свежая сессия.

        BUGFIX #2: SELECT ... FOR UPDATE на bot_payments больше не
        удерживается во время синхронного вызова Payment.find_one
        (до 15 сек). Сначала быстрая проверка без блокировки, потом
        API, потом повторная блокировка с повторной проверкой is_paid.
        Это убирает long-held lock и риск lock_timeout при массовых
        вебхуках.
        """
        # ЛЕНИВЫЙ ИМПОРТ — обходит циклический импорт
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

        # === Обработка отмен и возвратов ===
        if event in ("payment.canceled", "refund.succeeded"):
            stmt = select(BotPayment).where(BotPayment.payment_id == payment_id)
            db_payment = (await session.execute(stmt)).scalar_one_or_none()
            if db_payment:
                now = datetime.now(timezone.utc)
                if event == "payment.canceled":
                    if not db_payment.is_paid:
                        db_payment.status = "canceled"
                        db_payment.updated_at = now
                        logger.info(
                            f"✅ Webhook {payment_id}: status → canceled"
                        )
                elif event == "refund.succeeded":
                    db_payment.status = "refunded"
                    db_payment.updated_at = now
                    if db_payment.is_paid:
                        logger.warning(
                            f"⚠️ Webhook {payment_id}: refund for PAID payment"
                        )
                        await send_admin_alert(
                            f"⚠️ Возврат по оплаченному платежу {payment_id}. "
                            f"Подписка НЕ отозвана автоматически — "
                            f"проверьте пользователя {db_payment.telegram_id} вручную."
                        )
                    else:
                        logger.info(
                            f"✅ Webhook {payment_id}: status → refunded"
                        )
            return True

        if event != "payment.succeeded":
            logger.info(f"⏭️ Webhook {payment_id}: event={event} acknowledged")
            return True

        # === 1. Быстрая проверка без блокировки ===
        stmt = select(BotPayment).where(BotPayment.payment_id == payment_id)
        db_payment = (await session.execute(stmt)).scalar_one_or_none()
        if not db_payment:
            # BUGFIX: раньше здесь был `return False` → internal_api отдавал
            # 400 → ЮKassa считала вебхук доставленным и НЕ повторяла.
            # Теперь: 500 → ЮKassa повторяет.
            logger.error(f"❌ Webhook {payment_id}: not found in DB")
            await send_admin_alert(
                f"⚠️ Платёж {payment_id} не найден в БД. "
                f"Вебхук будет повторён автоматически."
            )
            raise YookassaTransientError(
                f"Payment {payment_id} not found in DB"
            )

        if db_payment.is_paid:
            logger.info(f"ℹ️ Webhook {payment_id}: already processed")
            return True

        # === 2. Double-check через API ЮKassa (без FOR UPDATE) ===
        loop = asyncio.get_running_loop()
        try:
            verified = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: Payment.find_one(payment_id)),
                timeout=15.0,
            )
        except Exception as e:
            logger.error(f"❌ Webhook {payment_id}: double-check failed: {e}")
            await send_admin_alert(
                f"⚠️ ЮKassa API недоступен при double-check платежа "
                f"{payment_id}: {e}. Вебхук будет повторён автоматически."
            )
            raise YookassaTransientError(
                f"YooKassa API unavailable for {payment_id}: {e}"
            ) from e

        if verified.status != "succeeded":
            logger.warning(
                f"⚠️ Webhook {payment_id}: status mismatch (API={verified.status})"
            )
            await send_admin_alert(
                f"⚠️ Статус API={verified.status} для платежа {payment_id} "
                f"(вебхук: payment.succeeded)"
            )
            return False

        if verified.amount is None or verified.amount.value is None:
            logger.error(f"❌ Webhook {payment_id}: API не вернул сумму")
            await send_admin_alert(
                f"⚠️ ЮKassa не вернула сумму по платежу {payment_id}"
            )
            return False

        verified_amount = float(verified.amount.value)
        verified_metadata = getattr(verified, "metadata", None) or {}

        # === 3. Повторная блокировка и повторная проверка is_paid ===
        stmt = (
            select(BotPayment)
            .where(BotPayment.payment_id == payment_id)
            .with_for_update()
        )
        db_payment = (await session.execute(stmt)).scalar_one_or_none()
        if not db_payment:
            logger.error(
                f"❌ Webhook {payment_id}: disappeared between checks"
            )
            raise YookassaTransientError(
                f"Payment {payment_id} disappeared between checks"
            )
        if db_payment.is_paid:
            logger.info(
                f"ℹ️ Webhook {payment_id}: processed by concurrent handler"
            )
            return True

        # === 4. Сверка суммы ===
        if abs(float(db_payment.amount) - verified_amount) > 0.01:
            logger.critical(f"🚨 Webhook {payment_id}: amount mismatch!")
            await send_admin_alert(f"🚨 Несовпадение суммы для платежа {payment_id}")
            return False

        # === 5. Метаданные ===
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

        if str(telegram_id) != str(metadata_telegram_id):
            logger.error(
                f"❌ Webhook {payment_id}: telegram_id mismatch "
                f"(db={telegram_id}, metadata={metadata_telegram_id})"
            )
            await send_admin_alert("⚠️ Подозрительный платёж: ID не совпадает")
            return False

        # === 6. Продление подписки ===
        # BUGFIX: убран skip_locked=True — иначе при параллельной
        # транзакции (/grant) SELECT возвращал None, и activate_subscription
        # обновлял строку без блокировки, теряя одно из продлений.
        stmt_user = (
            select(BotUser)
            .where(BotUser.telegram_id == telegram_id)
            .with_for_update()
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

        # === 7. Сообщение + фоновое создание ключа ===
        if product_type == "vpn" and bot:
            days = settings.PERIOD_DAYS.get(period, 0)
            vpn_end = user.vpn_subscription_end if user else None
            msg = Texts.payment_success_with_date(vpn_end, days, None)

            try:
                await bot.send_message(telegram_id, msg, parse_mode="Markdown")
            except TelegramForbiddenError:
                logger.info(
                    f"Webhook {payment_id}: user {telegram_id} blocked bot "
                    f"(activation msg)"
                )
            except TelegramAPIError as e:
                logger.warning(
                    f"Webhook {payment_id}: send activation msg failed: {e}"
                )

            async def _create_key_task():
                try:
                    vpn_manager = get_vpn_manager()
                    if vpn_manager:
                        link = await vpn_manager.get_or_create_link(telegram_id)
                        if link:
                            try:
                                await bot.send_message(
                                    telegram_id,
                                    f"🔗 Ваш ключ:\n`{link}`",
                                    parse_mode="Markdown",
                                )
                                logger.info(
                                    f"✅ Webhook {payment_id}: key sent"
                                )
                            except TelegramForbiddenError:
                                logger.info(
                                    f"Webhook {payment_id}: user "
                                    f"{telegram_id} blocked bot (key)"
                                )
                            except TelegramAPIError as e:
                                logger.warning(
                                    f"Webhook {payment_id}: send key failed: {e}"
                                )
                except asyncio.CancelledError:
                    logger.info(
                        f"Webhook {payment_id}: key task cancelled (shutdown)"
                    )
                    raise
                except Exception as e:
                    logger.error(
                        f"❌ Webhook {payment_id}: key creation error: {e}"
                    )
                    await send_admin_alert(
                        f"❌ Ошибка создания ключа для {telegram_id}: {e}"
                    )

            _schedule_key_task(_create_key_task())

        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
        logger.info(f"✅ Webhook {payment_id}: done in {elapsed:.2f}s")
        return True


yookassa_service = YookassaService()
logger.info("✅ YookassaService готов к работе")