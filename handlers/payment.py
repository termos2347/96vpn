# handlers/payment.py
import asyncio
import logging
import uuid

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message

from admin.bot import log_error
from config import settings
from db.base import AsyncSessionLocal
from db.models import BotPayment
from handlers.ui import Keyboards, Texts
from services.payment_yookassa import yookassa_service
from utils.decorators import rate_limit
from utils.validators import ValidationError, validate_currency, validate_user_id

logger = logging.getLogger(__name__)
router = Router(name="payment")


async def safe_answer_callback(
    callback: CallbackQuery, text: str | None = None, show_alert: bool = False
):
    try:
        if text:
            await callback.answer(text, show_alert=show_alert)
        else:
            await callback.answer()
    except TelegramBadRequest as e:
        if "query is too old" in str(e):
            logger.debug(f"Callback {callback.id} already expired, skipping answer.")
        else:
            raise


@router.callback_query(F.data.startswith("tariff_"))
@rate_limit(max_per_minute=settings.RATE_LIMIT_PAYMENT)
async def tariff_chosen(callback: CallbackQuery):
    if not isinstance(callback.message, Message):
        await safe_answer_callback(
            callback, "❌ Сообщение устарело", show_alert=True
        )
        return

    data = callback.data
    if not data:
        await safe_answer_callback(callback, "❌ Ошибка данных", show_alert=True)
        return

    try:
        parts = data.split("_")
        if len(parts) != 3:
            raise ValidationError(f"Invalid tariff callback: {data}")
        period = parts[1]
        currency = parts[2]

        validate_user_id(callback.from_user.id)
        validate_currency(currency)
        if period not in settings.PERIOD_DAYS:
            raise ValidationError(f"Invalid period: {period}")

        price = settings.VPN_PRICES[currency][period]
        user_id = callback.from_user.id

        # BUGFIX: ЮKassa требует строковые значения в metadata.
        # Раньше передавали int — SDK либо падал, либо молча приводил
        # к строке (не полагаемся на это). Приводим явно.
        metadata = {
            "source": "bot",
            "telegram_id": str(user_id),
            "product_type": "vpn",
            "period": period,
            "currency": currency.upper(),
        }
        description = f"Подписка {period} ({currency})"

        # 1) СНАЧАЛА создаём платёж в ЮKassa и получаем настоящий ID.
        # Это закрывает окно гонки: вебхук не может прийти раньше,
        # чем пользователь оплатит — а значит к моменту вебхука
        # запись в БД уже точно будет с правильным payment_id.
        payment = await yookassa_service.create_payment(price, description, metadata)
        if not payment:
            await safe_answer_callback(
                callback, "❌ Ошибка создания платежа", show_alert=True
            )
            return

        yookassa_id = payment.get("payment_id")
        url = payment.get("confirmation_url")
        if not url or not yookassa_id:
            await safe_answer_callback(
                callback, "❌ Не удалось получить ссылку на оплату", show_alert=True
            )
            return

        # 2) Вставляем запись с реальным payment_id.
        try:
            async with AsyncSessionLocal() as session, session.begin():
                session.add(
                    BotPayment(
                        payment_id=yookassa_id,
                        telegram_id=user_id,
                        amount=price,
                        currency=currency.upper(),
                        status="pending",
                        is_paid=False,
                    )
                )
        except Exception as db_err:
            logger.exception(
                f"Failed to save payment {yookassa_id} for user {user_id}: {db_err}"
            )
            log_error(
                f"Платёж {yookassa_id} создан в ЮKassa, но не сохранён в БД: "
                f"{db_err}",
                notify_admin=True,
            )

            # Best-effort отмена платежа в ЮKassa, чтобы не оставлять
            # "висящий" pending-платёж. URL пользователю НЕ показывали —
            # оплатить он не мог, но чистоту наводим.
            try:
                from yookassa import Payment as YooPayment

                idem_key = str(uuid.uuid4())
                await asyncio.wait_for(
                    asyncio.get_running_loop().run_in_executor(
                        None, YooPayment.cancel, yookassa_id, idem_key
                    ),
                    timeout=5.0,
                )
                logger.info(
                    f"Payment {yookassa_id} cancelled after DB error"
                )
            except Exception as cancel_err:
                logger.warning(
                    f"Failed to cancel payment {yookassa_id}: {cancel_err}"
                )

            await safe_answer_callback(
                callback,
                "❌ Системная ошибка. Платёж не был показан — повторите попытку. "
                "Если деньги списались — обратитесь в поддержку.",
                show_alert=True,
            )
            return

        # 3) Показываем ссылку на оплату
        try:
            await callback.message.edit_text(
                Texts.payment_link(price, currency, period),
                reply_markup=Keyboards.payment_url_button(url),
                disable_web_page_preview=True,
            )
        except TelegramBadRequest as e:
            if "message not found" in str(e):
                await callback.message.answer(
                    Texts.payment_link(price, currency, period),
                    reply_markup=Keyboards.payment_url_button(url),
                    disable_web_page_preview=True,
                )
            else:
                raise

        await safe_answer_callback(callback)
    except ValidationError as e:
        logger.warning(f"Validation error in tariff_chosen: {e}")
        await safe_answer_callback(
            callback, "❌ Некорректные параметры", show_alert=True
        )
    except Exception as e:
        logger.exception("Error in tariff_chosen")
        log_error(
            f"Payment error for user {callback.from_user.id}: {e}", notify_admin=True
        )
        await safe_answer_callback(
            callback, "❌ Внутренняя ошибка сервера", show_alert=True
        )
