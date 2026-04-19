from aiogram import Router, F, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from db.crud import set_vpn_subscription, set_bypass_subscription

router = Router()

# ---------- Вспомогательная функция для символа валюты ----------
def currency_symbol(currency: str) -> str:
    if currency == "rub":
        return "₽"
    elif currency == "stars":
        return "⭐"
    elif currency == "usdt":
        return "₿"
    return ""

# ---------- VPN ----------
@router.message(F.text == "💳 Оплатить VPN")
async def pay_vpn(message: types.Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇷🇺 Рубли (₽)", callback_data="vpn_currency_rub")],
        [InlineKeyboardButton(text="⭐ Telegram Stars", callback_data="vpn_currency_stars")],
        [InlineKeyboardButton(text="₿ USDT (TRC20)", callback_data="vpn_currency_usdt")]
    ])
    await message.answer("💎 Выберите валюту для оплаты VPN:", reply_markup=keyboard)

@router.callback_query(F.data.startswith("vpn_currency_"))
async def vpn_choose_period(callback: types.CallbackQuery):
    currency = callback.data.split("_")[-1]  # rub, stars, usdt
    prices = {
        "rub": {"1m": 300, "3m": 800, "6m": 1400},
        "stars": {"1m": 150, "3m": 400, "6m": 700},
        "usdt": {"1m": 3.5, "3m": 9.0, "6m": 16.0}
    }
    price_data = prices[currency]
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"1 месяц — {price_data['1m']} {currency_symbol(currency)}", callback_data=f"vpn_1m_{currency}")],
        [InlineKeyboardButton(text=f"3 месяца — {price_data['3m']} {currency_symbol(currency)}", callback_data=f"vpn_3m_{currency}")],
        [InlineKeyboardButton(text=f"6 месяцев — {price_data['6m']} {currency_symbol(currency)}", callback_data=f"vpn_6m_{currency}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="vpn_back_to_currency")]
    ])
    await callback.message.edit_text("📅 Выберите период подписки:", reply_markup=keyboard)
    await callback.answer()

@router.callback_query(F.data == "vpn_back_to_currency")
async def vpn_back_to_currency(callback: types.CallbackQuery):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇷🇺 Рубли (₽)", callback_data="vpn_currency_rub")],
        [InlineKeyboardButton(text="⭐ Telegram Stars", callback_data="vpn_currency_stars")],
        [InlineKeyboardButton(text="₿ USDT (TRC20)", callback_data="vpn_currency_usdt")]
    ])
    await callback.message.edit_text("💎 Выберите валюту для оплаты VPN:", reply_markup=keyboard)
    await callback.answer()

@router.callback_query(F.data.startswith("vpn_"))
async def vpn_process_payment(callback: types.CallbackQuery):
    # Формат: vpn_1m_rub, vpn_3m_stars и т.д.
    if callback.data == "vpn_back_to_currency":
        return  # уже обработано выше
    parts = callback.data.split("_")
    period = parts[1]   # 1m, 3m, 6m
    currency = parts[2] # rub, stars, usdt
    days_map = {"1m": 30, "3m": 90, "6m": 180}
    days = days_map[period]
    user_id = callback.from_user.id

    # Здесь будет реальная интеграция с платёжной системой
    # Пока имитируем успешную оплату
    await set_vpn_subscription(user_id, days)
    await callback.message.edit_text(
        f"✅ VPN подписка на {days} дней активирована!\n"
        f"Оплата: {period} через {currency.upper()}\n"
        f"Теперь вы можете подключиться в разделе 🚀 Подключить VPN"
    )
    await callback.answer()

# ---------- Bypass (обход) ----------
@router.message(F.text == "💰 Оплатить обход")
async def pay_bypass(message: types.Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇷🇺 Рубли (₽)", callback_data="bypass_currency_rub")],
        [InlineKeyboardButton(text="⭐ Telegram Stars", callback_data="bypass_currency_stars")],
        [InlineKeyboardButton(text="₿ USDT (TRC20)", callback_data="bypass_currency_usdt")]
    ])
    await message.answer("🔓 Выберите валюту для оплаты обхода блокировок:", reply_markup=keyboard)

@router.callback_query(F.data.startswith("bypass_currency_"))
async def bypass_choose_period(callback: types.CallbackQuery):
    currency = callback.data.split("_")[-1]
    prices = {
        "rub": {"1m": 150, "3m": 400},
        "stars": {"1m": 75, "3m": 200},
        "usdt": {"1m": 2.0, "3m": 4.5}
    }
    price_data = prices[currency]
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"1 месяц — {price_data['1m']} {currency_symbol(currency)}", callback_data=f"bypass_1m_{currency}")],
        [InlineKeyboardButton(text=f"3 месяца — {price_data['3m']} {currency_symbol(currency)}", callback_data=f"bypass_3m_{currency}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="bypass_back_to_currency")]
    ])
    await callback.message.edit_text("📅 Выберите период подписки на обход:", reply_markup=keyboard)
    await callback.answer()

@router.callback_query(F.data == "bypass_back_to_currency")
async def bypass_back_to_currency(callback: types.CallbackQuery):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇷🇺 Рубли (₽)", callback_data="bypass_currency_rub")],
        [InlineKeyboardButton(text="⭐ Telegram Stars", callback_data="bypass_currency_stars")],
        [InlineKeyboardButton(text="₿ USDT (TRC20)", callback_data="bypass_currency_usdt")]
    ])
    await callback.message.edit_text("🔓 Выберите валюту для оплаты обхода блокировок:", reply_markup=keyboard)
    await callback.answer()

@router.callback_query(F.data.startswith("bypass_"))
async def bypass_process_payment(callback: types.CallbackQuery):
    if callback.data == "bypass_back_to_currency":
        return
    parts = callback.data.split("_")
    period = parts[1]   # 1m, 3m
    currency = parts[2]
    days_map = {"1m": 30, "3m": 90}
    days = days_map[period]
    user_id = callback.from_user.id

    await set_bypass_subscription(user_id, days)
    await callback.message.edit_text(
        f"✅ Подписка на обход блокировок на {days} дней активирована!\n"
        f"Оплата: {period} через {currency.upper()}\n"
        f"Теперь вы можете подключиться в разделе 🛡️ Подключить обход"
    )
    await callback.answer()