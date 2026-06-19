import logging
from datetime import datetime, timezone
from aiogram import Router, F, types
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from db.base import AsyncSessionLocal
from db.crud import activate_subscription, update_bypass_subscription, update_vpn_subscription 
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

@router.message(F.successful_payment)
async def successful_payment(message: types.Message):
    payment = message.successful_payment
    payload = payment.invoice_payload
    telegram_payment_id = payment.telegram_payment_charge_id

    parts = payload.split("_")
    if len(parts) < 3:
        await message.answer("❌ Ошибка формата платежа.")
        return
    product_type, period, user_id_str = parts[0], parts[1], parts[2]
    target_user_id = int(user_id_str)
    if message.from_user.id != target_user_id:
        await message.answer("⚠️ Вы не можете оплатить подписку для другого пользователя.")
        return

    # Атомарно активируем подписку — только один раз
    success = False
    try:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                success = await activate_subscription(
                    session,
                    target_user_id,
                    product_type,
                    period,
                    telegram_payment_id
                )
    except Exception as e:
        logger.exception(f"Activation error for payment {telegram_payment_id}")
        await message.answer("❌ Ошибка при активации подписки. Обратитесь в поддержку.")
        return

    if not success:
        await message.answer("✅ Платёж уже обработан.")
        return

    # После активации создаём VPN-ключ (если нужно)
    days = PERIOD_DAYS.get(period, 0)
    if product_type == "vpn":
        try:
            vpn_manager = get_vpn_manager()
            if vpn_manager:
                link = await vpn_manager.create_key(target_user_id, days)
                if link:
                    await message.answer(f"✅ VPN подписка на {days} дней активирована!\n🔗 {link}")
                else:
                    await message.answer(f"✅ Подписка активирована, но ключ не создан. Обратитесь в поддержку.")
            else:
                await message.answer(f"✅ VPN подписка на {days} дней активирована! (сервис ключей временно недоступен)")
        except Exception as e:
            logger.exception(f"Key creation failed for user {target_user_id}")
            await message.answer(f"✅ Подписка активирована, но произошла ошибка при создании ключа. Мы исправим в ближайшее время.")
    else:
        await message.answer(f"✅ Обход DPI на {days} дней активирован!")