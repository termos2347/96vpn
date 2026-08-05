# handlers/payment.py
import logging
import uuid
from aiogram import Router, F, types
from aiogram.types import CallbackQuery, Message
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy import select

from handlers.ui import Texts, Keyboards
from db.base import AsyncSessionLocal
from db.models import BotPayment, BotUser
from db.crud import activate_subscription
from config import settings
from services.payment_yookassa import yookassa_service
from services.vpn_manager import get_vpn_manager
from admin import send_admin_alert
from admin.bot import log_error
from utils.decorators import rate_limit
from utils.validators import validate_user_id, validate_currency, ValidationError

logger = logging.getLogger(__name__)
router = Router(name="payment")


# ---------- Вспомогательная функция для безопасного ответа на callback ----------
async def safe_answer_callback(callback: CallbackQuery, text: str = None, show_alert: bool = False):
    """Безопасно отвечает на callback, игнорируя ошибку 'query is too old'."""
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


# ---------- Выбор валюты ----------
@router.callback_query(F.data.startswith("currency_"))
@rate_limit(max_per_minute=settings.RATE_LIMIT_TARIFF)
async def currency_chosen(callback: CallbackQuery):
    """Пользователь выбрал валюту → показываем тарифы для этой валюты."""
    try:
        currency = callback.data.split("_")[1]
        if currency not in settings.VPN_PRICES:
            raise ValidationError(f"Invalid currency: {currency}")

        new_text = Texts.tariff_selection(currency)
        new_markup = Keyboards.tariff_selection(currency)

        # Проверяем, нужно ли обновлять сообщение
        current_text = callback.message.text
        current_markup = callback.message.reply_markup
        # Сравниваем по содержимому (для упрощения сравниваем строки)
        if current_text == new_text and current_markup == new_markup:
            # Сообщение уже такое же – просто отвечаем на callback
            await safe_answer_callback(callback)
            return

        await callback.message.edit_text(
            new_text,
            reply_markup=new_markup
        )
        await safe_answer_callback(callback)
    except ValidationError as e:
        logger.warning(f"Validation error in currency_chosen: {e}")
        await safe_answer_callback(callback, "❌ Некорректная валюта", show_alert=True)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            # Игнорируем, сообщение уже содержит нужный контент
            logger.debug("Message already has the same content, ignoring.")
            await safe_answer_callback(callback)
        else:
            logger.exception(f"Telegram error in currency_chosen: {e}")
            await safe_answer_callback(callback, "❌ Ошибка обновления", show_alert=True)
    except Exception as e:
        logger.exception(f"Error in currency_chosen: {e}")
        await safe_answer_callback(callback, "❌ Внутренняя ошибка", show_alert=True)


# ---------- Выбор тарифа (с валютой) ----------
@router.callback_query(F.data.startswith("tariff_"))
@rate_limit(max_per_minute=settings.RATE_LIMIT_PAYMENT)
async def tariff_chosen(callback: CallbackQuery):
    """
    Обработчик выбора тарифа.
    Callback имеет вид tariff_{period}_{currency}, например tariff_1m_rub.
    Сразу создаём платёж.
    """
    try:
        parts = callback.data.split("_")
        if len(parts) != 3:
            raise ValidationError(f"Invalid tariff callback: {callback.data}")
        period = parts[1]
        currency = parts[2]

        validate_user_id(callback.from_user.id)
        validate_currency(currency)
        if period not in settings.PERIOD_DAYS:
            raise ValidationError(f"Invalid period: {period}")

        price = settings.VPN_PRICES[currency][period]
        user_id = callback.from_user.id

        # Создаём временную запись платежа в БД (pending)
        local_tx_id = f"tmp_{uuid.uuid4().hex[:16]}"
        async with AsyncSessionLocal() as session:
            async with session.begin():
                new_payment = BotPayment(
                    payment_id=local_tx_id,
                    telegram_id=user_id,
                    amount=price,
                    currency=currency.upper(),
                    status="pending",
                    is_paid=False
                )
                session.add(new_payment)

        # Вызываем Yookassa
        metadata = {
            "source": "bot",
            "telegram_id": user_id,
            "product_type": "vpn",
            "period": period,
            "currency": currency.upper()
        }
        description = f"Подписка {period} ({currency})"
        payment = await yookassa_service.create_payment(price, description, metadata)

        if not payment:
            await safe_answer_callback(callback, "❌ Ошибка создания платежа", show_alert=True)
            return

        yookassa_id = payment.get("payment_id")
        url = payment.get("confirmation_url")
        if not url or not yookassa_id:
            await safe_answer_callback(callback, "❌ Не удалось получить ссылку на оплату", show_alert=True)
            return

        # Обновляем запись платежа реальным ID от Yookassa
        async with AsyncSessionLocal() as session:
            async with session.begin():
                stmt = select(BotPayment).where(BotPayment.payment_id == local_tx_id)
                res = await session.execute(stmt)
                db_payment = res.scalar_one_or_none()
                if db_payment:
                    db_payment.payment_id = yookassa_id
                else:
                    logger.error(f"Local payment {local_tx_id} vanished!")
                    await safe_answer_callback(callback, "❌ Системная ошибка", show_alert=True)
                    return

        # Показываем ссылку на оплату
        try:
            await callback.message.edit_text(
                Texts.payment_link(price, currency, period),
                reply_markup=Keyboards.payment_url_button(url),
                disable_web_page_preview=True
            )
        except TelegramBadRequest as e:
            if "message not found" in str(e):
                await callback.message.answer(
                    Texts.payment_link(price, currency, period),
                    reply_markup=Keyboards.payment_url_button(url),
                    disable_web_page_preview=True
                )
            else:
                raise

        await safe_answer_callback(callback)
    except ValidationError as e:
        logger.warning(f"Validation error in tariff_chosen: {e}")
        await safe_answer_callback(callback, "❌ Некорректные параметры", show_alert=True)
    except Exception as e:
        logger.exception(f"Error in tariff_chosen: {e}")
        log_error(f"Payment error for user {callback.from_user.id}: {e}", notify_admin=True)
        await safe_answer_callback(callback, "❌ Внутренняя ошибка сервера", show_alert=True)


# ---------- Обработка успешного платежа через Stars (если используется) ----------
@router.pre_checkout_query()
async def pre_checkout(pre_checkout_query: types.PreCheckoutQuery):
    await pre_checkout_query.answer(ok=True)


@router.message(F.successful_payment)
@rate_limit(max_per_minute=settings.RATE_LIMIT_STARS)
async def successful_payment(message: Message):
    payment = message.successful_payment
    payload = payment.invoice_payload
    telegram_payment_id = payment.telegram_payment_charge_id

    # Ожидаем payload вида: vpn_1m_rub_<user_id> (или аналогично для bypass)
    parts = payload.split("_")
    if len(parts) < 4:
        await message.answer(Texts.payment_error())
        return
    product_type, period, currency, user_id_str = parts[0], parts[1], parts[2], parts[3]
    target_user_id = int(user_id_str)

    if message.from_user.id != target_user_id:
        await message.answer("⚠️ Вы не можете оплатить подписку для другого пользователя.")
        return

    async with AsyncSessionLocal() as session:
        stmt = select(BotPayment).where(BotPayment.payment_id == telegram_payment_id)
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing and existing.is_paid:
            await message.answer(Texts.payment_already_processed())
            return

    success = False
    try:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                stmt_user = select(BotUser).where(BotUser.telegram_id == target_user_id).with_for_update()
                user = (await session.execute(stmt_user)).scalar_one_or_none()
                if not user:
                    user = BotUser(telegram_id=target_user_id)
                    session.add(user)
                    await session.flush()
                    # повторная блокировка
                    stmt_user = select(BotUser).where(BotUser.telegram_id == target_user_id).with_for_update()
                    user = (await session.execute(stmt_user)).scalar_one()

                success = await activate_subscription(
                    session,
                    target_user_id,
                    product_type,
                    period,
                    telegram_payment_id,
                    user=user
                )
    except Exception as e:
        logger.exception(f"Activation error for payment {telegram_payment_id}")
        log_error(f"Activation error: {e}", notify_admin=True)
        await message.answer(Texts.payment_error())
        return

    if not success:
        await message.answer(Texts.payment_already_processed())
        return

    days = settings.PERIOD_DAYS.get(period, 0)
    if product_type == "vpn":
        try:
            async with AsyncSessionLocal() as session:
                stmt = select(BotUser).where(BotUser.telegram_id == target_user_id)
                user = (await session.execute(stmt)).scalar_one_or_none()
                vpn_end = user.vpn_subscription_end if user else None

            vpn_manager = get_vpn_manager()
            if vpn_manager:
                link = await vpn_manager.create_key(target_user_id, days)
            else:
                link = None

            msg = Texts.payment_success_with_date(vpn_end, days, link)
            await message.answer(msg, parse_mode="Markdown")

            if not link and vpn_manager:
                await send_admin_alert(f"⚠️ Не удалось создать ключ для {target_user_id}")
        except Exception as e:
            logger.exception(f"Key creation failed for user {target_user_id}")
            log_error(f"Key creation failed: {e}", notify_admin=True)
            await message.answer(Texts.key_creation_error())
            await send_admin_alert(f"❌ Ошибка создания ключа для {target_user_id}: {e}")
    else:
        await message.answer(f"✅ Подписка на {product_type} на {days} дней активирована!")