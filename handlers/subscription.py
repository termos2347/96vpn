from aiogram import Router, F, types
from datetime import datetime
from db.crud import is_subscription_active, get_subscription_end

router = Router()

@router.message(F.text == "🚀 Подключить VPN")
async def connect_vpn(message: types.Message):
    user_id = message.from_user.id
    end = await get_subscription_end(user_id)
    active = await is_subscription_active(user_id)
    await message.answer(f"Debug: end={end}, now={datetime.now()}, active={active}")
    if active:
        await message.answer(
            "✅ Ваша подписка активна!\n"
            "Вот ваш конфиг (пока тестовый):\n"
            "`vless://test@example.com:443?security=tls`",
            parse_mode="Markdown"
        )
    else:
        await message.answer(
            "❌ У вас нет активной подписки.\n"
            "Оплатите тариф в разделе 💳 Оплатить VPN."
        )

@router.message(F.text == "🛡️ Подключить обход")
async def connect_bypass(message: types.Message):
    user_id = message.from_user.id
    if await is_subscription_active(user_id):
        await message.answer(
            "✅ Обход блокировок активен.\n"
            "Настройте прокси в Telegram: `tg://proxy?server=...&port=...`",
            parse_mode="Markdown"
        )
    else:
        await message.answer(
            "❌ У вас нет активной подписки на обход.\n"
            "Оплатите в разделе 💰 Оплатить обход."
        )