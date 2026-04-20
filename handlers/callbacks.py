from aiogram.filters.callback_data import CallbackData

class VPNCurrencyCallback(CallbackData, prefix="vpn_currency"):
    currency: str

class VPNPeriodCallback(CallbackData, prefix="vpn_period"):
    period: str  # "1m", "3m", "6m"
    currency: str

class BypassCurrencyCallback(CallbackData, prefix="bypass_currency"):
    currency: str

class BypassPeriodCallback(CallbackData, prefix="bypass_period"):
    period: str  # "1m", "3m"
    currency: str

class BackCallback(CallbackData, prefix="back"):
    target: str  # "vpn_currency" или "bypass_currency"