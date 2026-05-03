import asyncio
import logging
from collections import deque

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import BotCommand
from sqlalchemy import text, select

from config import ADMIN_BOT_TOKEN, ADMIN_CHAT_ID, TOKEN as MAIN_BOT_TOKEN
from db.base import engine, AsyncSessionLocal
from db.models import User
from services.vpn_provider import vpn_provider

logger = logging.getLogger(__name__)

error_log = deque(maxlen=10)
admin_bot: Bot | None = None
main_bot: Bot | None = None

async def send_admin_alert(message: str):
    """Отправить алерт админу."""
    global admin_bot
    if not admin_bot or not ADMIN_CHAT_ID:
        logger.warning("Admin bot not initialized, alert not sent")
        return
    try:
        await admin_bot.send_message(ADMIN_CHAT_ID, f"🚨 {message}")
    except Exception as e:
        logger.error(f"Failed to send admin alert: {e}")

async def startup():
    global admin_bot, main_bot
    admin_bot = Bot(token=ADMIN_BOT_TOKEN)
    main_bot = Bot(token=MAIN_BOT_TOKEN)
    await admin_bot.set_my_commands([
        BotCommand(command="health", description="Проверка состояния"),
        BotCommand(command="errors", description="Последние ошибки"),
        BotCommand(command="broadcast", description="Рассылка текста (reply на сообщение)"),
    ])
    logger.info("Admin bot started")

async def shutdown():
    global admin_bot, main_bot
    if admin_bot:
        await admin_bot.session.close()
        admin_bot = None
    if main_bot:
        await main_bot.session.close()
        main_bot = None
    logger.info("Admin bot stopped")

dp = Dispatcher()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("🛡️ Админ-бот 96VPN. Доступные команды:\n/health\n/errors\n/broadcast (reply на сообщение)")

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

@dp.message(Command("broadcast"))
async def cmd_broadcast(message: types.Message):
    # Проверка прав администратора
    if str(message.from_user.id) != ADMIN_CHAT_ID:
        await message.answer("❌ Нет доступа.")
        return

    # Должен быть ответ на сообщение
    if not message.reply_to_message:
        await message.answer("❗ Ответьте на сообщение, которое нужно разослать, и пришлите /broadcast.")
        return

    # Извлекаем текст из сообщения, на которое ответили
    text_to_send = message.reply_to_message.text or message.reply_to_message.caption
    if not text_to_send:
        await message.answer("❗ В отвечаемом сообщении нет текста. Напишите текст и ответьте на него.")
        return

    # Получаем список пользователей, которые запускали основного бота
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User.user_id).where(
                User.user_id.isnot(None),
                User.source == "bot"
            )
        )
        user_ids = [row[0] for row in result.all()]

    if not user_ids:
        await message.answer("Нет клиентов для рассылки.")
        return

    await message.answer(f"Рассылка текста на {len(user_ids)} клиентов началась...")
    success = 0
    fail = 0

    for uid in user_ids:
        try:
            await main_bot.send_message(uid, text_to_send)
            success += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.info(f"Broadcast could not deliver to {uid}: {e}")
            fail += 1

    await message.answer(f"✅ Рассылка завершена: отправлено {success}, ошибок {fail}.")

async def start_polling():
    await startup()
    for attempt in range(5):
        try:
            await dp.start_polling(admin_bot)
            break
        except Exception as e:
            logger.warning(f"Admin polling attempt {attempt+1} failed: {e}")
            await asyncio.sleep(2)
    else:
        logger.error("Could not start admin polling after 5 attempts")