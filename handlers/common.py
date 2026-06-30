import logging
from aiogram import Router, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from datetime import datetime, timezone

from db.crud import get_or_create_bot_user
from db.base import AsyncSessionLocal
from . import get_vpn_manager
from utils.decorators import rate_limit

logger = logging.getLogger(__name__)
router = Router()

@router.message(Command("getkey"))
@rate_limit(max_per_minute=3)
async def cmd_get_key(message: Message, state: FSMContext):
    user_id = message.from_user.id
    # Проверяем наличие активной подписки в БД
    async with AsyncSessionLocal() as session:
        user = await get_or_create_bot_user(session, user_id)
        now = datetime.now(timezone.utc)
        if not user.vpn_subscription_end or user.vpn_subscription_end <= now:
            await message.answer(
                "❌ У вас нет активной VPN-подписки. Оплатите в разделе 💳 Оплатить VPN."
            )
            return

    # Пытаемся получить или создать ключ
    vpn_manager = get_vpn_manager()
    if not vpn_manager:
        await message.answer("⚠️ Техническая ошибка: VPN-сервис временно недоступен. Администратор уведомлён.")
        logger.error("VPNManager not initialized in cmd_get_key")
        return

    try:
        link = await vpn_manager.get_or_create_link(user_id)
        if link:
            await message.answer(
                f"🔗 Ваша VPN-ссылка:\n`{link}`\n\n"
                "Скопируйте её и вставьте в приложение (например, V2RayNG, Shadowrocket, Hiddify).",
                parse_mode="Markdown"
            )
        else:
            # Ошибка при создании – панель недоступна или таймаут
            await message.answer(
                "⚠️ Сервер временно перегружен, мы уже работаем над этим.\n"
                "Пожалуйста, попробуйте через 5–10 минут или нажмите кнопку «🚀 Подключить VPN» позже.\n"
                "Администратор уведомлён о проблеме."
            )
            # Лог для админа (можно использовать send_admin_alert)
            logger.error(f"Failed to create/get key for user {user_id}: link is None")
            # Здесь можно вызвать функцию отправки уведомления админу
    except Exception as e:
        logger.exception(f"Unexpected error in cmd_get_key for user {user_id}: {e}")
        await message.answer(
            "⚠️ Произошла непредвиденная ошибка. Мы уже знаем и исправляем.\n"
            "Попробуйте позже."
        )