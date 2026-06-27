import logging
from aiogram import Router, F, types
from admin.bot import log_error
from db.crud import is_vpn_active, get_vpn_client_id
from utils.decorators import rate_limit
from utils.validators import validate_user_id, ValidationError
from config import settings
from handlers import get_vpn_manager

logger = logging.getLogger(__name__)
router = Router()

@router.message(F.text == "🚀 Подключить VPN")
@rate_limit(max_per_minute=10)
async def connect_vpn(message: types.Message):
    try:
        user_id = message.from_user.id
        validate_user_id(user_id)

        active = await is_vpn_active(user_id)
        if not active:
            logger.info(f"User {user_id} tried to connect without active subscription")
            await message.answer(
                "❌ У вас нет активной VPN подписки.\n\n"
                "💳 Оплатите подписку в разделе '💳 Оплатить VPN'"
            )
            return

        client_id = await get_vpn_client_id(user_id)
        if not client_id:
            logger.warning(f"User {user_id} has active subscription but no client_id, will create new key")

        vpn_manager = get_vpn_manager()
        if not vpn_manager:
            await message.answer("⚠️ Сервис временно недоступен. Попробуйте позже.")
            return

        link = await vpn_manager.get_or_create_link(user_id)
        if link:
            logger.info(f"VPN link generated for user {user_id}")
            await message.answer(
                f"✅ Ваша VPN подписка активна!\n\n"
                f"🔗 Ссылка для подключения:\n`{link}`\n\n"
                f"💡 Скопируйте ссылку и вставьте в VPN приложение",
                parse_mode="Markdown"
            )
        else:
            logger.error(f"Failed to get/create VPN link for user {user_id}")
            await message.answer(
                "⚠️ Не удалось получить ключ VPN.\n\n"
                f"Попробуйте позже или обратитесь в поддержку: @{settings.SUPPORT_USERNAME}"
            )

    except ValidationError as e:
        logger.warning(f"Validation error in connect_vpn: {e}")
        log_error(f"Validation error in connect_vpn for user {user_id}: {e}", notify_admin=False)  # <-- добавлен log_error
        await message.answer("❌ Ошибка при получении ссылки. Попробуйте позже.")
    except Exception as e:
        logger.error(f"Exception in connect_vpn", exc_info=True)
        log_error(f"Exception in connect_vpn for user {user_id}: {e}", notify_admin=True)  # <-- добавлен log_error
        await message.answer("❌ Произошла ошибка. Попробуйте позже.")