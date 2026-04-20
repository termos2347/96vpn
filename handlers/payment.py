from aiogram import Router, F, types
from db.crud import set_vpn_subscription, set_bypass_subscription, is_vpn_active
from .callbacks import (
    VPNCurrencyCallback, VPNPeriodCallback,
    BypassCurrencyCallback, BypassPeriodCallback,
    BackCallback
)
from .keyboards import (
    vpn_currency_keyboard, vpn_period_keyboard,
    bypass_currency_keyboard, bypass_period_keyboard
)

router = Router()

# ---------- VPN ----------
@router.message(F.text == "💳 Оплатить VPN")
async def pay_vpn(message: types.Message):
    await message.answer("💎 Выберите валюту для оплаты VPN:", reply_markup=vpn_currency_keyboard())

@router.callback_query(VPNCurrencyCallback.filter())
async def vpn_choose_period(callback: types.CallbackQuery, callback_data: VPNCurrencyCallback):
    currency = callback_data.currency
    await callback.message.edit_text(
        "📅 Выберите период подписки:",
        reply_markup=vpn_period_keyboard(currency)
    )
    await callback.answer()

@router.callback_query(BackCallback.filter(F.target == "vpn_currency"))
async def vpn_back_to_currency(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "💎 Выберите валюту для оплаты VPN:",
        reply_markup=vpn_currency_keyboard()
    )
    await callback.answer()

@router.callback_query(VPNPeriodCallback.filter())
async def vpn_process_payment(callback: types.CallbackQuery, callback_data: VPNPeriodCallback):
    days_map = {"1m": 30, "3m": 90, "6m": 180}
    days = days_map[callback_data.period]
    user_id = callback.from_user.id

    await set_vpn_subscription(user_id, days)
    await callback.message.edit_text(
        f"✅ VPN подписка на {days} дней активирована!\n"
        f"Оплата: {callback_data.period} через {callback_data.currency.upper()}\n"
        f"Теперь вы можете подключиться в разделе 🚀 Подключить VPN"
    )
    await callback.answer()

# ---------- Bypass (обход) ----------
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

@router.callback_query(BypassCurrencyCallback.filter())
async def bypass_choose_period(callback: types.CallbackQuery, callback_data: BypassCurrencyCallback):
    currency = callback_data.currency
    await callback.message.edit_text(
        "📅 Выберите период подписки на обход:",
        reply_markup=bypass_period_keyboard(currency)
    )
    await callback.answer()

@router.callback_query(BackCallback.filter(F.target == "bypass_currency"))
async def bypass_back_to_currency(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "🔓 Выберите валюту для оплаты обхода блокировок:",
        reply_markup=bypass_currency_keyboard()
    )
    await callback.answer()

@router.callback_query(BypassPeriodCallback.filter())
async def bypass_process_payment(callback: types.CallbackQuery, callback_data: BypassPeriodCallback):
    user_id = callback.from_user.id
    if not await is_vpn_active(user_id):
        await callback.message.edit_text(
            "❌ Ваша VPN-подписка не активна. Оплата обхода невозможна.\n"
            "Оплатите VPN в разделе 💳 Оплатить VPN."
        )
        await callback.answer()
        return

    days_map = {"1m": 30, "3m": 90}
    days = days_map[callback_data.period]
    currency = callback_data.currency

    await set_bypass_subscription(user_id, days)
    await callback.message.edit_text(
        f"✅ Подписка на обход блокировок на {days} дней активирована!\n"
        f"Оплата: {callback_data.period} через {currency.upper()}\n"
        f"Теперь вы можете подключиться в разделе 🛡️ Подключить обход"
    )
    await callback.answer()