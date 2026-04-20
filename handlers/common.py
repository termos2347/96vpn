from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.types import BotCommand
from db.crud import get_vpn_end, get_bypass_end, is_bypass_active
from datetime import datetime
from .keyboards import main_keyboard

router = Router()

async def setup_bot_commands(bot):
    commands = [
        BotCommand(command="start", description="🚀 Главное меню"),
    ]
    await bot.set_my_commands(commands)

@router.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "Добро пожаловать! Выберите нужный раздел в меню ниже:",
        reply_markup=main_keyboard()
    )

@router.message(F.text == "ℹ️ Инфо")
async def info(message: types.Message):
    user_id = message.from_user.id
    
    vpn_end = await get_vpn_end(user_id)
    vpn_status = "❌ не активна"
    if vpn_end and vpn_end > datetime.now():
        days_left = (vpn_end - datetime.now()).days
        vpn_status = f"✅ активна, осталось {days_left} дн."
    
    bypass_active = await is_bypass_active(user_id)
    bypass_status = "✅ активна" if bypass_active else "❌ не активна"
    
    await message.answer(
        "📌 Информация о подписках:\n\n"
        f"🚀 VPN: {vpn_status}\n"
        f"🛡️ Обход: {bypass_status}\n\n"
        "О сервисе:\n"
        "— Высокоскоростные серверы в 5 странах\n"
        "— Протоколы: VLESS, Shadowsocks, WireGuard\n"
        "— Защита от утечек DNS и IPv6\n"
        "— Круглосуточная поддержка\n\n"
        "По вопросам: @support_username"
    )