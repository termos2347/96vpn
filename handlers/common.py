import logging
from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.types import BotCommand
from aiogram.exceptions import TelegramForbiddenError
from db.crud import get_vpn_end, get_bypass_end, is_bypass_active, get_or_create_bot_user
from datetime import datetime
from utils.decorators import rate_limit
from utils.validators import validate_user_id, ValidationError
from .keyboards import main_keyboard

logger = logging.getLogger(__name__)
router = Router()

async def setup_bot_commands(bot):
    commands = [
        BotCommand(command="start", description="🚀 Главное меню"),
    ]
    await bot.set_my_commands(commands)

@router.message(Command("start"))
@rate_limit(max_per_minute=10)
async def cmd_start(message: types.Message):
    try:
        user_id = message.from_user.id
        username = message.from_user.username
        
        validate_user_id(user_id)
        await get_or_create_bot_user(user_id, username)
        
        logger.info(f"User {user_id} (@{username}) started the bot")
        
        await message.answer(
            "🎉 Добро пожаловать в 96VPN Bot!\n\n"
            "Выберите нужный раздел в меню ниже:",
            reply_markup=main_keyboard()
        )
    except TelegramForbiddenError:
        logger.info(f"User {message.from_user.id} blocked the bot")
    except ValidationError as e:
        logger.warning(f"Validation error in /start: {e}")
        try:
            await message.answer("❌ Ошибка при инициализации. Попробуйте позже.")
        except TelegramForbiddenError:
            pass
    except Exception as e:
        logger.error(f"Exception in /start: {e}", exc_info=True)
        try:
            await message.answer("❌ Произошла ошибка. Попробуйте позже.")
        except TelegramForbiddenError:
            pass

@router.message(F.text == "ℹ️ Инфо")
@rate_limit(max_per_minute=10)
async def info(message: types.Message):
    try:
        user_id = message.from_user.id
        validate_user_id(user_id)
        
        vpn_end = await get_vpn_end(user_id)
        vpn_status = "❌ не активна"
        if vpn_end and vpn_end > datetime.now():
            days_left = (vpn_end - datetime.now()).days
            vpn_status = f"✅ активна, осталось {days_left} дн."
        
        bypass_active = await is_bypass_active(user_id)
        bypass_status = "✅ активна" if bypass_active else "❌ не активна"
        
        logger.info(f"User {user_id} requested info (VPN: {vpn_status}, Bypass: {bypass_status})")
        
        await message.answer(
            "📌 Информация о подписках:\n\n"
            f"🚀 VPN: {vpn_status}\n"
            f"🛡️ Обход DPI: {bypass_status}\n\n"
            "ℹ️ О сервисе:\n"
            "— Высокоскоростные серверы в 5 странах\n"
            "— Протоколы: VLESS, Shadowsocks, WireGuard\n"
            "— Защита от утечек DNS и IPv6\n"
            "— Круглосуточная поддержка\n\n"
            "📞 По вопросам: @support_username"
        )
    except ValidationError as e:
        logger.warning(f"Validation error in info: {e}")
        await message.answer("❌ Ошибка при получении информации.")
    except Exception as e:
        logger.error(f"Exception in info: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка при получении информации.")