import logging
from datetime import datetime, timezone
from aiogram import Router, F, types
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from db.crud import set_vpn_subscription, log_bot_payment, is_bot_payment_processed
from config import settings
from services.payment_yookassa import yookassa_service
from handlers.keyboards import vpn_currency_keyboard, vpn_period_keyboard
from utils.decorators import rate_limit
from utils.validators import validate_user_id, validate_currency, ValidationError
from handlers import get_vpn_manager

logger = logging.getLogger(__name__)
router = Router()
PERIOD_DAYS = {"1m": 30, "3m": 90, "6m": 180}

# ---------- Оплата через ЮKassa (RUB, USDT) ----------
@router.message(F.text == "💳 Оплатить VPN")
@rate_limit(max_per_minute=10)
async def pay_vpn(message: types.Message):
    try:
        validate_user_id(message.from_user.id)
        await message.answer("💎 Выберите валюту для оплаты VPN:", reply_markup=vpn_currency_keyboard())
    except ValidationError as e:
        logger.warning(f"Validation error in pay_vpn: {e}")
        await message.answer("❌ Ошибка валидации. Попробуйте позже.")

@router.callback_query(F.data.startswith("vpn_currency_"))
@rate_limit(max_per_minute=10)
async def vpn_choose_period(callback: types.CallbackQuery):
    try:
        validate_user_id(callback.from_user.id)
        currency = callback.data.split("_")[-1]
        validate_currency(currency)
        await callback.message.edit_text(
            "📅 Выберите период подписки:",
            reply_markup=vpn_period_keyboard(currency)
        )
        await callback.answer()
    except ValidationError as e:
        logger.warning(f"Validation error: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)

@router.callback_query(F.data.regexp(r"^vpn_(1m|3m|6m)_(rub|usdt)$"))
@rate_limit(max_per_minute=5)
async def vpn_payment_rub_usdt(callback: types.CallbackQuery):
    _, period, currency = callback.data.split("_")
    user_id = callback.from_user.id
    price = settings.VPN_PRICES[currency][period]
    description = f"VPN подписка {period} ({currency})"

    # Создаём платёж в ЮKassa
    metadata = {
        "source": "bot",
        "telegram_id": user_id,
        "product_type": "vpn",
        "period": period,
        "currency": currency
    }
    payment = await yookassa_service.create_payment(price, description, metadata)
    if not payment:
        await callback.answer("❌ Ошибка создания платежа", show_alert=True)
        return

    # Отправляем пользователю ссылку на оплату
    url = payment["confirmation_url"]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплатить", url=url)]
    ])
    await callback.message.delete()
    await callback.message.answer(
        f"💳 Ссылка для оплаты VPN ({period}, {price} {currency}):\n\n"
        f"После оплаты подписка активируется автоматически.",
        reply_markup=kb
    )
    await callback.answer()

# ---------- Оплата через Telegram Stars ----------
@router.pre_checkout_query()
async def pre_checkout(pre_checkout_query: types.PreCheckoutQuery):
    await pre_checkout_query.answer(ok=True)

@router.message(F.successful_payment)
async def successful_payment(message: types.Message):
    payment = message.successful_payment
    payload = payment.invoice_payload          # "vpn_1m_123456"
    telegram_payment_id = payment.telegram_payment_charge_id
    logger.info(f"⭐ Successful Stars payment: payload={payload}, payment_id={telegram_payment_id}")

    if await is_bot_payment_processed(telegram_payment_id):
        logger.info(f"Duplicate Stars payment {telegram_payment_id} ignored")
        await message.answer("✅ Этот платёж уже был обработан.")
        return

    parts = payload.split("_")
    if len(parts) < 3:
        logger.error(f"Invalid invoice payload: {payload}")
        return
    product_type, period, user_id_str = parts[0], parts[1], parts[2]
    user_id = int(user_id_str)
    days = PERIOD_DAYS.get(period, 0)

    if product_type == "vpn":
        await set_vpn_subscription(user_id, days)
        await log_bot_payment(telegram_payment_id, user_id)

        vpn_manager = get_vpn_manager()
        if vpn_manager:
            link = await vpn_manager.create_key(user_id, days)
            if link:
                await message.answer(f"✅ VPN подписка на {days} дней активирована!\n🔗 Ваша ссылка: {link}")
            else:
                await message.answer(f"✅ VPN подписка на {days} дней активирована, но ключ не создан. Обратитесь в поддержку.")
        else:
            await message.answer(f"✅ VPN подписка на {days} дней активирована!")
    else:
        logger.warning(f"Unknown product type: {product_type}")