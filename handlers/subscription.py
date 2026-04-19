from aiogram import Router, F, types
from datetime import datetime
from db.crud import is_vpn_active, is_bypass_active, get_vpn_end, get_bypass_end

router = Router()

@router.message(F.text == "🚀 Подключить VPN")
async def connect_vpn(message: types.Message):
    user_id = message.from_user.id
    active = await is_vpn_active(user_id)
    end = await get_vpn_end(user_id)
    await message.answer(f"Debug VPN: end={end}, now={datetime.now()}, active={active}")
    if active:
        await message.answer(
            "✅ Ваша VPN подписка активна!\n"
            "Вот ваш конфиг (пока тестовый):\n"
            "`vless://test@example.com:443?security=tls`",
            parse_mode="Markdown"
        )
    else:
        await message.answer(
            "❌ У вас нет активной VPN подписки.\n"
            "Оплатите в разделе 💳 Оплатить VPN."
        )

@router.message(F.text == "🛡️ Подключить обход")
async def connect_bypass(message: types.Message):
    user_id = message.from_user.id
    active = await is_bypass_active(user_id)
    end = await get_bypass_end(user_id)
    await message.answer(f"Debug Bypass: end={end}, now={datetime.now()}, active={active}")
    if active:
        await message.answer(
            "✅ Ваша подписка на обход блокировок активна!\n"
            "Настройте прокси в Telegram по ссылке (скоро появится)."
        )
    else:
        await message.answer(
            "❌ У вас нет активной подписки на обход.\n"
            "Оплатите в разделе 💰 Оплатить обход."
        )