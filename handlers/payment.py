from aiogram import Router, F, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from db.crud import set_vpn_subscription, set_bypass_subscription

router = Router()

# Обработчик кнопки "Оплатить VPN"
@router.message(F.text == "💳 Оплатить VPN")
async def pay_vpn(message: types.Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1 месяц — 5$", callback_data="vpn_1m")],
        [InlineKeyboardButton(text="3 месяца — 12$", callback_data="vpn_3m")],
        [InlineKeyboardButton(text="6 месяцев — 20$", callback_data="vpn_6m")]
    ])
    await message.answer("Выберите тариф VPN:", reply_markup=keyboard)

@router.callback_query(F.data.startswith("vpn_"))
async def process_vpn_payment(callback: types.CallbackQuery):
    days_map = {
        "vpn_1m": 30,
        "vpn_3m": 90,
        "vpn_6m": 180,
    }
    days = days_map.get(callback.data)
    if days:
        user_id = callback.from_user.id
        await set_vpn_subscription(user_id, days)
        await callback.message.answer(f"✅ VPN подписка на {days} дней активирована (тестовый режим).")
    else:
        await callback.message.answer("Ошибка выбора тарифа.")
    await callback.answer()

# Обработчик кнопки "Оплатить обход"
@router.message(F.text == "💰 Оплатить обход")
async def pay_bypass(message: types.Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1 месяц — 3$", callback_data="bypass_1m")],
        [InlineKeyboardButton(text="3 месяца — 8$", callback_data="bypass_3m")]
    ])
    await message.answer("Выберите тариф для обхода блокировок:", reply_markup=keyboard)

@router.callback_query(F.data.startswith("bypass_"))
async def process_bypass_payment(callback: types.CallbackQuery):
    days_map = {
        "bypass_1m": 30,
        "bypass_3m": 90,
    }
    days = days_map.get(callback.data)
    if days:
        user_id = callback.from_user.id
        await set_bypass_subscription(user_id, days)
        await callback.message.answer(f"✅ Подписка на обход на {days} дней активирована (тестовый режим).")
    else:
        await callback.message.answer("Ошибка выбора тарифа.")
    await callback.answer()