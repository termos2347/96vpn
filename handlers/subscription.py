from aiogram import Router, F, types
from db.crud import is_vpn_active, get_vpn_client_id, set_vpn_client_id
from services.vpn_provider import XUIVPNProvider

router = Router()
vpn_provider = XUIVPNProvider()

@router.message(F.text == "🚀 Подключить VPN")
async def connect_vpn(message: types.Message):
    user_id = message.from_user.id
    if not await is_vpn_active(user_id):
        await message.answer("❌ У вас нет активной VPN подписки.\nОплатите в разделе 💳 Оплатить VPN.")
        return

    client_uuid = await get_vpn_client_id(user_id)
    if not client_uuid:
        # Пробуем создать заново (на случай, если запись потерялась)
        email = f"user_{user_id}@96vpn.bot"
        client_uuid = await vpn_provider.create_client(email)
        if client_uuid:
            await set_vpn_client_id(user_id, client_uuid)
        else:
            await message.answer("⚠️ Не удалось получить ключ. Попробуйте позже или обратитесь в поддержку.")
            return

    config = await vpn_provider.get_client_config(client_uuid)
    if config:
        await message.answer(
            f"✅ Ваша VPN подписка активна!\nВаш конфиг:\n`{config}`",
            parse_mode="Markdown"
        )
    else:
        await message.answer("⚠️ Не удалось сгенерировать конфиг. Обратитесь в поддержку.")