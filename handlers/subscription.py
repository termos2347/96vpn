import logging
from aiogram import Router, F, types
from db.crud import is_vpn_active, get_vpn_client_id, set_vpn_client_id
from services.vpn_provider import XUIVPNProvider
from utils.decorators import rate_limit
from utils.validators import validate_user_id, ValidationError
from services.vpn_provider import vpn_provider

logger = logging.getLogger(__name__)
router = Router()

@router.message(F.text == "🚀 Подключить VPN")
@rate_limit(max_per_minute=10)
async def connect_vpn(message: types.Message):
    """Показывает ссылку подписки пользователю."""
    try:
        user_id = message.from_user.id
        validate_user_id(user_id)
        
        # Проверяем наличие активной подписки
        if not await is_vpn_active(user_id):
            logger.info(f"User {user_id} tried to connect without active subscription")
            await message.answer(
                "❌ У вас нет активной VPN подписки.\n\n"
                "💳 Оплатите подписку в разделе '💳 Оплатить VPN'"
            )
            return
        
        # Постоянный email для поиска/создания клиента на панели
        email = f"user_{user_id}@96vpn.bot"
        logger.info(f"User {user_id} requesting VPN connection link")
        
        # Ищем существующего клиента
        client_data = await vpn_provider.get_client_by_email(email)
        
        if not client_data:
            # Если не найден (например, после ручной активации старого формата), создаём
            logger.info(f"Client {email} not found on panel, creating new...")
            client_data = await vpn_provider.create_client(email)
        
        if client_data and client_data.get("subId"):
            sub_id = client_data["subId"]
            # Сохраняем UUID в БД, если ещё не сохранён
            if not await get_vpn_client_id(user_id):
                await set_vpn_client_id(user_id, client_data["uuid"])
            link = vpn_provider.get_subscription_link(sub_id)
            
            logger.info(f"VPN link generated for user {user_id}")
            
            await message.answer(
                f"✅ Ваша VPN подписка активна!\n\n"
                f"🔗 Ссылка для подключения:\n`{link}`\n\n"
                f"💡 Скопируйте ссылку и вставьте в VPN приложение",
                parse_mode="Markdown"
            )
        else:
            logger.error(f"Failed to get/create client for user {user_id}")
            await message.answer(
                "⚠️ Не удалось получить ключ VPN.\n\n"
                "Попробуйте позже или обратитесь в поддержку: @support_username"
            )
    
    except ValidationError as e:
        logger.warning(f"Validation error in connect_vpn: {e}")
        await message.answer("❌ Ошибка при получении ссылки. Попробуйте позже.")
    except Exception as e:
        logger.error(f"Exception in connect_vpn: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка. Попробуйте позже.")