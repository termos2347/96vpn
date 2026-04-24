import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiohttp import ClientTimeout, TCPConnector, ClientSession
from config import TOKEN, PROXY_URL
from handlers import router
from handlers.common import setup_bot_commands
from services.scheduler import start_scheduler
from db.base import init_db  # <-- новый импорт

async def main():
    logging.basicConfig(level=logging.INFO)
    
    await init_db()
    
    session = None
    if PROXY_URL:
        # Создаём кастомный коннектор с большими лимитами
        connector = TCPConnector(
            limit=100,
            limit_per_host=30,
            ttl_dns_cache=300,
            force_close=False,
            enable_cleanup_closed=True,
        )
        timeout = ClientTimeout(
            total=60,          # общий таймаут на запрос
            connect=20,        # на установку соединения
            sock_read=30,      # на чтение данных
            sock_connect=20,   # на подключение сокета
        )
        # Создаём ClientSession и передаём её в AiohttpSession
        client_session = ClientSession(
            connector=connector,
            timeout=timeout,
        )
        session = AiohttpSession(proxy=PROXY_URL)
        # Подменяем внутреннюю сессию на нашу кастомную
        session._session = client_session
        logging.info(f"Using HTTP proxy with custom timeouts: {PROXY_URL}")
    
    bot = Bot(token=TOKEN, session=session)
    dp = Dispatcher()
    
    await start_scheduler(bot)
    await setup_bot_commands(bot)
    dp.include_router(router)
    
    # Бесконечный цикл с перезапуском при падении поллинга
    while True:
        try:
            await dp.start_polling(bot)
        except Exception as e:
            logging.error(f"Polling crashed: {e}. Restarting in 5 seconds...")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())