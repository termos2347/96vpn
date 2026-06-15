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

    url = payment.get("confirmation_url")
    if not url:
        await callback.answer("❌ Не удалось получить ссылку на оплату", show_alert=True)
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплатить", url=url)]
    ])
    await callback.message.delete()
    await callback.message.answer(
        f"💳 Ссылка для оплаты VPN ({period}, {price} {currency}):\n\n"
        f"После оплаты подписка активируется автоматически.\n"
        f"Если вы уже оплачивали ранее, новая подписка добавится к текущей.",
        reply_markup=kb
    )
    await callback.answer()

# ---------- Оплата через Telegram Stars ----------
@router.pre_checkout_query()
async def pre_checkout(pre_checkout_query: types.PreCheckoutQuery):
    await pre_checkout_query.answer(ok=True)

# handlers/payment.py (фрагмент с исправлением)

@router.message(F.successful_payment)
async def successful_payment(message: types.Message):
    payment = message.successful_payment
    payload = payment.invoice_payload          # "vpn_1m_123456"
    telegram_payment_id = payment.telegram_payment_charge_id
    logger.info(f"⭐ Successful Stars payment: payload={payload}, payment_id={telegram_payment_id}")

    # 1. Проверка на дубликат
    if await is_bot_payment_processed(telegram_payment_id):
        logger.info(f"Duplicate Stars payment {telegram_payment_id} ignored")
        await message.answer("✅ Этот платёж уже был обработан.")
        return

    # 2. Разбор payload
    parts = payload.split("_")
    if len(parts) < 3:
        logger.error(f"Invalid invoice payload: {payload}")
        await message.answer("❌ Ошибка: некорректный формат платежа. Обратитесь в поддержку.")
        return

    product_type, period, user_id_str = parts[0], parts[1], parts[2]
    try:
        target_user_id = int(user_id_str)
    except ValueError:
        logger.error(f"Invalid user_id in payload: {user_id_str}")
        await message.answer("❌ Ошибка: неверный идентификатор пользователя. Обратитесь в поддержку.")
        return

    # 3. КРИТИЧЕСКАЯ ПРОВЕРКА: плательщик должен совпадать с получателем
    if message.from_user.id != target_user_id:
        logger.error(
            f"Stars payment user mismatch: payer={message.from_user.id}, "
            f"target={target_user_id}, payment_id={telegram_payment_id}"
        )
        await message.answer(
            "⚠️ Вы попытались оплатить подписку для другого пользователя.\n"
            "Это запрещено из соображений безопасности.\n\n"
            "Платёж не был активирован. Пожалуйста, обратитесь в поддержку "
            f"@{settings.SUPPORT_USERNAME} для возврата средств."
        )
        # Дополнительно можно уведомить администратора
        from admin.bot import send_admin_alert
        await send_admin_alert(
            f"Stars payment rejected: payer {message.from_user.id} tried to "
            f"activate for user {target_user_id}, payment_id={telegram_payment_id}"
        )
        return

    days = PERIOD_DAYS.get(period, 0)
    if days == 0:
        logger.error(f"Unknown period in payload: {period}")
        await message.answer("❌ Неизвестный период подписки. Обратитесь в поддержку.")
        return

    # 4. Активация подписки (только для VPN, так как bypass временно отключён)
    if product_type == "vpn":
        await set_vpn_subscription(target_user_id, days)
        await log_bot_payment(telegram_payment_id, target_user_id)

        vpn_manager = get_vpn_manager()
        if vpn_manager:
            link = await vpn_manager.create_key(target_user_id, days)
            if link:
                await message.answer(
                    f"✅ VPN подписка на {days} дней активирована!\n"
                    f"🔗 Ваша ссылка: {link}"
                )
            else:
                await message.answer(
                    f"✅ VPN подписка на {days} дней активирована, "
                    f"но ключ не создан. Обратитесь в поддержку."
                )
        else:
            await message.answer(f"✅ VPN подписка на {days} дней активирована!")
    else:
        logger.warning(f"Unknown product type: {product_type}")
        await message.answer("❌ Неизвестный тип подписки. Обратитесь в поддержку.")