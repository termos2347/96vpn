from aiogram import Router, F, types
from db.crud import is_vpn_active, get_vpn_client_id, set_vpn_client_id
from services.vpn_provider import XUIVPNProvider
import logging

router = Router()
vpn_provider = XUIVPNProvider()
logger = logging.getLogger(__name__)

@router.message(F.text == "🚀 Подключить VPN")
async def connect_vpn(message: types.Message):
    user_id = message.from_user.id
    if not await is_vpn_active(user_id):
        await message.answer("❌ У вас нет активной VPN подписки.\nОплатите в разделе 💳 Оплатить VPN.")
        return

    email = f"user_{user_id}@96vpn.bot"
    
    # 1. Пытаемся получить существующего клиента с сервера
    client_data = await vpn_provider.get_client_by_email(email)
    
    if not client_data:
        # Клиент не найден на сервере – создаём нового
        logger.info(f"Клиент {email} не найден на сервере, создаю нового")
        client_data = await vpn_provider.create_client(email)
    
    if client_data:
        sub_id = client_data["subId"]
        # Сохраняем актуальный subId в БД
        await set_vpn_client_id(user_id, sub_id)
        link = vpn_provider.get_subscription_link(sub_id)
        await message.answer(
            f"✅ Ваша VPN подписка активна!\n🔗 Ссылка для подключения:\n`{link}`",
            parse_mode="Markdown"
        )
    else:
        await message.answer("⚠️ Не удалось получить ключ. Попробуйте позже или обратитесь в поддержку.")