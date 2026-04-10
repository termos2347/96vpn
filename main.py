import asyncio
import logging
from aiogram import Bot, Dispatcher
from config import TOKEN
from db.base import init_db
from handlers import router
from handlers.common import setup_bot_commands   # <-- импорт

async def main():
    logging.basicConfig(level=logging.INFO)
    await init_db()
    bot = Bot(token=TOKEN)
    dp = Dispatcher()
    
    # Устанавливаем команды для кнопки "Меню"
    await setup_bot_commands(bot)
    
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())