import asyncio
import logging
from aiogram import Bot, Dispatcher
from config import TOKEN
from db.base import init_db
from handlers import router

async def main():
    logging.basicConfig(level=logging.INFO)
    await init_db()          # создаст таблицы, если их нет
    bot = Bot(token=TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())