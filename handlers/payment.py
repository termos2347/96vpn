from aiogram import Router, F, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from db.crud import set_subscription

router = Router()

@router.message(F.text == "💳 Оплатить VPN")
async def pay_vpn(message: types.Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1 месяц — 5$", callback_data="sub_1m")],
        [InlineKeyboardButton(text="3 месяца — 12$", callback_data="sub_3m")],
        [InlineKeyboardButton(text="6 месяцев — 20$", callback_data="sub_6m")]
    ])
    await message.answer("Выберите тариф:", reply_markup=keyboard)

@router.callback_query(F.data.startswith("sub_"))
async def process_subscription(callback: types.CallbackQuery):
    days_map = {
        "sub_1m": 30,
        "sub_3m": 90,
        "sub_6m": 180,
    }
    days = days_map.get(callback.data)
    if days:
        user_id = callback.from_user.id
        # Сохраняем подписку в БД
        success = await set_subscription(user_id, days)
        if success:
            await callback.message.answer(f"✅ Подписка на {days} дней активирована (тестовый режим).")
        else:
            await callback.message.answer("❌ Не удалось активировать подписку. Пользователь не найден.")
    else:
        await callback.message.answer("Ошибка выбора тарифа.")
    await callback.answer()

@router.message(F.text == "💰 Оплатить обход")
async def pay_bypass(message: types.Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1 месяц — 3$", callback_data="bypass_1m")],
        [InlineKeyboardButton(text="3 месяца — 8$", callback_data="bypass_3m")]
    ])
    await message.answer("Выберите тариф для обхода блокировок:", reply_markup=keyboard)

@router.callback_query(F.data.startswith("bypass_"))
async def process_bypass_subscription(callback: types.CallbackQuery):
    days_map = {
        "bypass_1m": 30,
        "bypass_3m": 90,
    }
    days = days_map.get(callback.data)
    if days:
        user_id = callback.from_user.id
        success = await set_subscription(user_id, days)
        if success:
            await callback.message.answer(f"✅ Подписка на обход на {days} дней активирована (тестовый режим).")
        else:
            await callback.message.answer("❌ Не удалось активировать подписку.")
    else:
        await callback.message.answer("Ошибка выбора тарифа.")
    await callback.answer()