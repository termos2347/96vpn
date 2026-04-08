import asyncio
import logging
from aiogram import Bot, Dispatcher
import config    # Импортируем наш конфиг
from handlers import router  # Импортируем роутер из handlers.py

async def main():
    logging.basicConfig(level=logging.INFO)
    bot = Bot(token=config.TOKEN)
    dp = Dispatcher()
    
    # Важно: подключаем обработчики
    dp.include_router(router)
    
    print("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
