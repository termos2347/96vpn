from aiogram import Router, F, types
from aiogram.types import LabeledPrice, PreCheckoutQuery
from db.crud import set_vpn_subscription, set_bypass_subscription, is_vpn_active, set_vpn_client_id
from .keyboards import (
    vpn_currency_keyboard, vpn_period_keyboard,
    bypass_currency_keyboard, bypass_period_keyboard
)
from config import VPN_PRICES, BYPASS_PRICES
from services.vpn_provider import XUIVPNProvider

router = Router()
PERIOD_DAYS = {"1m": 30, "3m": 90, "6m": 180}
vpn_provider = XUIVPNProvider()  # создаём один раз при импорте

# ---------- VPN ----------
@router.message(F.text == "💳 Оплатить VPN")
async def pay_vpn(message: types.Message):
    await message.answer("💎 Выберите валюту для оплаты VPN:", reply_markup=vpn_currency_keyboard())

@router.callback_query(F.data.startswith("vpn_currency_"))
async def vpn_choose_period(callback: types.CallbackQuery):
    currency = callback.data.split("_")[-1]
    await callback.message.edit_text(
        "📅 Выберите период подписки:",
        reply_markup=vpn_period_keyboard(currency)
    )
    await callback.answer()

@router.callback_query(F.data == "vpn_back_to_currency")
async def vpn_back_to_currency(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "💎 Выберите валюту для оплаты VPN:",
        reply_markup=vpn_currency_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data.regexp(r"^vpn_(1m|3m|6m)_(rub|stars|usdt)$"))
async def vpn_process_payment(callback: types.CallbackQuery):
    data = callback.data
    _, period, currency = data.split("_")
    days = PERIOD_DAYS[period]
    user_id = callback.from_user.id

    if currency == "stars":
        price = VPN_PRICES["stars"][period]
        await callback.message.answer_invoice(
            title="VPN Подписка",
            description=f"Доступ к VPN на {days} дней",
            payload=f"vpn_{period}_{user_id}",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label="VPN Подписка", amount=price)],
            start_parameter="vpn_subscription",
        )
        await callback.answer()
        return

    # Для рублей и USDT – имитация оплаты
    await set_vpn_subscription(user_id, days)

    # Создаём клиента в 3x-ui
    email = f"user_{user_id}@96vpn.bot"
    client_uuid = await vpn_provider.create_client(email)
    if client_uuid:
        await set_vpn_client_id(user_id, client_uuid)
        config = await vpn_provider.get_client_config(client_uuid)
        if config:
            await callback.message.edit_text(
                f"✅ VPN подписка на {days} дней активирована!\n"
                f"Оплата: {period} через {currency.upper()}\n\n"
                f"Ваш конфиг для подключения:\n`{config}`",
                parse_mode="Markdown"
            )
        else:
            await callback.message.edit_text(
                f"✅ VPN подписка на {days} дней активирована!\n"
                f"Оплата: {period} через {currency.upper()}\n\n"
                f"⚠️ Не удалось сгенерировать конфиг автоматически.\n"
                f"Пожалуйста, нажмите 🚀 Подключить VPN позже или обратитесь в поддержку."
            )
    else:
        await callback.message.edit_text(
            f"✅ VPN подписка на {days} дней активирована!\n"
            f"Оплата: {period} через {currency.upper()}\n\n"
            f"⚠️ Не удалось создать ключ. Попробуйте позже или обратитесь в поддержку."
        )
    await callback.answer()

# ---------- Bypass ----------
@router.message(F.text == "💰 Оплатить обход")
async def pay_bypass(message: types.Message):
    user_id = message.from_user.id
    if not await is_vpn_active(user_id):
        await message.answer(
            "❌ Для оплаты обхода блокировок необходима активная VPN-подписка.\n"
            "Сначала оплатите VPN в разделе 💳 Оплатить VPN."
        )
        return
    await message.answer("🔓 Выберите валюту для оплаты обхода блокировок:", reply_markup=bypass_currency_keyboard())

@router.callback_query(F.data.startswith("bypass_currency_"))
async def bypass_choose_period(callback: types.CallbackQuery):
    currency = callback.data.split("_")[-1]
    await callback.message.edit_text(
        "📅 Выберите период подписки на обход:",
        reply_markup=bypass_period_keyboard(currency)
    )
    await callback.answer()

@router.callback_query(F.data == "bypass_back_to_currency")
async def bypass_back_to_currency(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "🔓 Выберите валюту для оплаты обхода блокировок:",
        reply_markup=bypass_currency_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data.regexp(r"^bypass_(1m|3m)_(rub|stars|usdt)$"))
async def bypass_process_payment(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if not await is_vpn_active(user_id):
        await callback.message.edit_text(
            "❌ Ваша VPN-подписка не активна. Оплата обхода невозможна.\n"
            "Оплатите VPN в разделе 💳 Оплатить VPN."
        )
        await callback.answer()
        return

    data = callback.data
    _, period, currency = data.split("_")
    days = PERIOD_DAYS[period]

    if currency == "stars":
        price = BYPASS_PRICES["stars"][period]
        await callback.message.answer_invoice(
            title="Обход блокировок",
            description=f"Доступ к обходу DPI на {days} дней",
            payload=f"bypass_{period}_{user_id}",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label="Обход блокировок", amount=price)],
            start_parameter="bypass_subscription",
        )
        await callback.answer()
    else:
        await set_bypass_subscription(user_id, days)
        await callback.message.edit_text(
            f"✅ Обход на {days} дней активирован!\n"
            f"Оплата: {period} через {currency.upper()}"
        )
        await callback.answer()

# ---------- Платежи Telegram Stars ----------
@router.pre_checkout_query()
async def pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await pre_checkout_query.answer(ok=True)

@router.message(F.successful_payment)
async def successful_payment(message: types.Message):
    payment = message.successful_payment
    payload = payment.invoice_payload  # "vpn_1m_123456" или "bypass_1m_123456"
    parts = payload.split("_")
    if len(parts) < 3:
        return
    product_type, period, user_id_str = parts[0], parts[1], parts[2]
    user_id = int(user_id_str)
    days = PERIOD_DAYS.get(period, 0)
    if product_type == "vpn":
        await set_vpn_subscription(user_id, days)
        await message.answer(f"✅ VPN подписка на {days} дней активирована!")
    elif product_type == "bypass":
        await set_bypass_subscription(user_id, days)
        await message.answer(f"✅ Обход на {days} дней активирован!")