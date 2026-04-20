from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from .callbacks import (
    VPNCurrencyCallback, VPNPeriodCallback,
    BypassCurrencyCallback, BypassPeriodCallback,
    BackCallback
)

# ---------- Вспомогательная функция для символа валюты ----------
def currency_symbol(currency: str) -> str:
    if currency == "rub":
        return "₽"
    elif currency == "stars":
        return "⭐"
    elif currency == "usdt":
        return "₿"
    return ""

# ---------- Главное меню (ReplyKeyboard) ----------
def main_keyboard() -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton(text="🚀 Подключить VPN"), KeyboardButton(text="🛡️ Подключить обход")],
        [KeyboardButton(text="💳 Оплатить VPN"), KeyboardButton(text="💰 Оплатить обход")],
        [KeyboardButton(text="ℹ️ Инфо"), KeyboardButton(text="🆓 Прокси")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

# ---------- Инлайн клавиатуры для VPN ----------
def vpn_currency_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇷🇺 Рубли (₽)", callback_data=VPNCurrencyCallback(currency="rub").pack())],
        [InlineKeyboardButton(text="⭐ Telegram Stars", callback_data=VPNCurrencyCallback(currency="stars").pack())],
        [InlineKeyboardButton(text="₿ USDT (TRC20)", callback_data=VPNCurrencyCallback(currency="usdt").pack())]
    ])

def vpn_period_keyboard(currency: str) -> InlineKeyboardMarkup:
    prices = {
        "rub": {"1m": 300, "3m": 800, "6m": 1400},
        "stars": {"1m": 150, "3m": 400, "6m": 700},
        "usdt": {"1m": 3.5, "3m": 9.0, "6m": 16.0}
    }
    price_data = prices[currency]
    sym = currency_symbol(currency)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"1 месяц — {price_data['1m']} {sym}",
            callback_data=VPNPeriodCallback(period="1m", currency=currency).pack()
        )],
        [InlineKeyboardButton(
            text=f"3 месяца — {price_data['3m']} {sym}",
            callback_data=VPNPeriodCallback(period="3m", currency=currency).pack()
        )],
        [InlineKeyboardButton(
            text=f"6 месяцев — {price_data['6m']} {sym}",
            callback_data=VPNPeriodCallback(period="6m", currency=currency).pack()
        )],
        [InlineKeyboardButton(
            text="🔙 Назад",
            callback_data=BackCallback(target="vpn_currency").pack()
        )]
    ])

# ---------- Инлайн клавиатуры для обхода (Bypass) ----------
def bypass_currency_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇷🇺 Рубли (₽)", callback_data=BypassCurrencyCallback(currency="rub").pack())],
        [InlineKeyboardButton(text="⭐ Telegram Stars", callback_data=BypassCurrencyCallback(currency="stars").pack())],
        [InlineKeyboardButton(text="₿ USDT (TRC20)", callback_data=BypassCurrencyCallback(currency="usdt").pack())]
    ])

def bypass_period_keyboard(currency: str) -> InlineKeyboardMarkup:
    prices = {
        "rub": {"1m": 150, "3m": 400},
        "stars": {"1m": 75, "3m": 200},
        "usdt": {"1m": 2.0, "3m": 4.5}
    }
    price_data = prices[currency]
    sym = currency_symbol(currency)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"1 месяц — {price_data['1m']} {sym}",
            callback_data=BypassPeriodCallback(period="1m", currency=currency).pack()
        )],
        [InlineKeyboardButton(
            text=f"3 месяца — {price_data['3m']} {sym}",
            callback_data=BypassPeriodCallback(period="3m", currency=currency).pack()
        )],
        [InlineKeyboardButton(
            text="🔙 Назад",
            callback_data=BackCallback(target="bypass_currency").pack()
        )]
    ])