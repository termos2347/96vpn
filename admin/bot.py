import logging
from sqlalchemy import text
from collections import deque
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import BotCommand
from config import ADMIN_BOT_TOKEN, ADMIN_CHAT_ID
from db.base import engine
from services.vpn_provider import vpn_provider

logger = logging.getLogger(__name__)

error_log = deque(maxlen=10)
admin_bot: Bot | None = None

async def send_admin_alert(message: str):
    """Отправить алерт админу (можно вызывать из любого места)."""
    global admin_bot
    if not admin_bot or not ADMIN_CHAT_ID:
        logger.warning("Admin bot not initialized, alert not sent")
        return
    try:
        await admin_bot.send_message(ADMIN_CHAT_ID, f"🚨 {message}")
    except Exception as e:
        logger.error(f"Failed to send admin alert: {e}")

async def startup():
    global admin_bot
    admin_bot = Bot(token=ADMIN_BOT_TOKEN)
    await admin_bot.set_my_commands([
        BotCommand(command="health", description="Проверка состояния"),
        BotCommand(command="errors", description="Последние ошибки"),
    ])
    logger.info("Admin bot started")

async def shutdown():
    global admin_bot
    if admin_bot:
        await admin_bot.session.close()
        admin_bot = None
    logger.info("Admin bot stopped")

dp = Dispatcher()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("🛡️ Админ-бот 96VPN. Доступные команды:\n/health\n/errors")

@dp.message(Command("health"))
async def cmd_health(message: types.Message):
    status = "✅ Статус:\n"
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        status += "• БД: подключена\n"
    except Exception as e:
        status += f"• БД: ошибка ({e})\n"

    try:
        if await vpn_provider.login():
            status += "• VPN-панель: авторизована\n"
        else:
            status += "• VPN-панель: не авторизована\n"
    except Exception as e:
        status += f"• VPN-панель: ошибка ({e})\n"

    await message.answer(status)

@dp.message(Command("errors"))
async def cmd_errors(message: types.Message):
    if not error_log:
        await message.answer("✅ Нет сохранённых ошибок.")
        return
    text = "📋 Последние ошибки:\n"
    for i, err in enumerate(reversed(error_log), 1):
        text += f"{i}. {err}\n"
    await message.answer(text)

async def start_polling():
    await startup()
    await dp.start_polling(admin_bot)