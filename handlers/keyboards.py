from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

def currency_symbol(currency: str) -> str:
    if currency == "rub":
        return "₽"
    elif currency == "stars":
        return "⭐"
    elif currency == "usdt":
        return "₿"
    return ""

def main_keyboard() -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton(text="🚀 Подключить VPN"), KeyboardButton(text="🛡️ Подключить обход")],
        [KeyboardButton(text="💳 Оплатить VPN"), KeyboardButton(text="💰 Оплатить обход")],
        [KeyboardButton(text="ℹ️ Инфо"), KeyboardButton(text="🆓 Прокси")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def vpn_currency_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇷🇺 Рубли (₽)", callback_data="vpn_currency_rub")],
        [InlineKeyboardButton(text="⭐ Telegram Stars", callback_data="vpn_currency_stars")],
        [InlineKeyboardButton(text="₿ USDT (TRC20)", callback_data="vpn_currency_usdt")],
    ])

def vpn_period_keyboard(currency: str) -> InlineKeyboardMarkup:
    from config import VPN_PRICES
    prices = VPN_PRICES[currency]
    sym = currency_symbol(currency)
    buttons = []
    for period, price in prices.items():
        text = f"{period_to_text(period)} — {price} {sym}"
        cb = f"vpn_{period}_{currency}"
        buttons.append([InlineKeyboardButton(text=text, callback_data=cb)])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="vpn_back_to_currency")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def bypass_currency_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇷🇺 Рубли (₽)", callback_data="bypass_currency_rub")],
        [InlineKeyboardButton(text="⭐ Telegram Stars", callback_data="bypass_currency_stars")],
        [InlineKeyboardButton(text="₿ USDT (TRC20)", callback_data="bypass_currency_usdt")],
    ])

def bypass_period_keyboard(currency: str) -> InlineKeyboardMarkup:
    from config import BYPASS_PRICES
    prices = BYPASS_PRICES[currency]
    sym = currency_symbol(currency)
    buttons = []
    for period, price in prices.items():
        text = f"{period_to_text(period)} — {price} {sym}"
        cb = f"bypass_{period}_{currency}"
        buttons.append([InlineKeyboardButton(text=text, callback_data=cb)])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="bypass_back_to_currency")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def period_to_text(period: str) -> str:
    return {"1m": "1 месяц", "3m": "3 месяца", "6m": "6 месяцев"}.get(period, period)