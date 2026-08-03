# handlers/payment.py
import logging
import uuid
from aiogram import Router, F, types
from aiogram.types import CallbackQuery, Message
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


# ---------- Обработчик выбора тарифа ----------
@router.callback_query(F.data.startswith("tariff_"))
@rate_limit(max_per_minute=settings.RATE_LIMIT_TARIFF)
async def tariff_chosen(callback: CallbackQuery):
    try:
        validate_user_id(callback.from_user.id)
        period = callback.data.split("_")[1]
        if period not in settings.PERIOD_DAYS:
            raise ValidationError(f"Invalid period: {period}")
        await callback.message.edit_text(
            Texts.payment_methods(),
            reply_markup=Keyboards.payment_methods(period)
        )
        await callback.answer()
    except ValidationError as e:
        logger.warning(f"Validation error in tariff_chosen: {e}")
        await callback.answer("❌ Ошибка выбора тарифа", show_alert=True)


# ---------- Обработчик выбора способа оплаты (Рубли/Stars/USDT) ----------
@router.callback_query(F.data.startswith("pay_"))
@rate_limit(max_per_minute=settings.RATE_LIMIT_PAYMENT)
async def process_payment(callback: CallbackQuery):
    _, period, currency = callback.data.split("_")
    user_id = callback.from_user.id
    try:
        validate_user_id(user_id)
        validate_currency(currency)
        if period not in settings.PERIOD_DAYS:
            raise ValidationError(f"Invalid period: {period}")
        price = settings.VPN_PRICES[currency][period]
    except ValidationError as e:
        logger.warning(f"Validation error in process_payment: {e}")
        await callback.answer("❌ Некорректные параметры", show_alert=True)
        return

    description = f"VPN подписка {period} ({currency})"
    db_currency = currency.upper()
    local_tx_id = f"tmp_{uuid.uuid4().hex[:16]}"

    try:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                new_payment = BotPayment(
                    payment_id=local_tx_id,
                    telegram_id=user_id,
                    amount=price,
                    currency=db_currency,
                    status="pending",
                    is_paid=False
                )
                session.add(new_payment)

        metadata = {
            "source": "bot",
            "telegram_id": user_id,
            "product_type": "vpn",
            "period": period,
            "currency": db_currency
        }

        payment = await yookassa_service.create_payment(price, description, metadata)
        if not payment:
            await callback.answer("❌ Ошибка создания платежа", show_alert=True)
            return

        yookassa_id = payment.get("payment_id")
        url = payment.get("confirmation_url")
        if not url or not yookassa_id:
            await callback.answer("❌ Не удалось получить ссылку на оплату", show_alert=True)
            return

        async with AsyncSessionLocal() as session:
            async with session.begin():
                stmt = select(BotPayment).where(BotPayment.payment_id == local_tx_id)
                res = await session.execute(stmt)
                db_payment = res.scalar_one_or_none()
                if db_payment:
                    db_payment.payment_id = yookassa_id
                else:
                    logger.error(f"Local payment {local_tx_id} vanished!")
                    await callback.answer("❌ Системная ошибка", show_alert=True)
                    return

        await callback.message.delete()
        await callback.message.answer(
            Texts.payment_link(price, currency, period),
            reply_markup=Keyboards.payment_url_button(url)
        )
        await callback.answer()

    except Exception as e:
        logger.error(f"Error in process_payment: {e}", exc_info=True)
        log_error(f"Payment error for user {user_id}: {e}", notify_admin=True)
        await callback.answer("❌ Внутренняя ошибка сервера", show_alert=True)


@router.pre_checkout_query()
async def pre_checkout(pre_checkout_query: types.PreCheckoutQuery):
    await pre_checkout_query.answer(ok=True)


@router.message(F.successful_payment)
@rate_limit(max_per_minute=settings.RATE_LIMIT_STARS)
async def successful_payment(message: Message):
    payment = message.successful_payment
    payload = payment.invoice_payload
    telegram_payment_id = payment.telegram_payment_charge_id

    parts = payload.split("_")
    if len(parts) < 3:
        await message.answer(Texts.payment_error())
        return
    product_type, period, user_id_str = parts[0], parts[1], parts[2]
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