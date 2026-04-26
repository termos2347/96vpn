import asyncio
import logging
import signal
import sys
from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiohttp import ClientTimeout, TCPConnector, ClientSession
from config import TOKEN, PROXY_URL
from handlers import router
from handlers.common import setup_bot_commands
from services.scheduler import start_scheduler
from db.base import init_db, engine
from utils.logger import setup_logger

async def main():
    # Настраиваем логирование
    setup_logger()
    logger = logging.getLogger(__name__)

    logger.info("Starting VPN bot...")

    try:
        await init_db()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}", exc_info=True)
        sys.exit(1)

    session = None
    if PROXY_URL:
        try:
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
            logger.info(f"Using HTTP proxy with custom timeouts: {PROXY_URL}")
        except Exception as e:
            logger.error(f"Failed to setup proxy session: {e}", exc_info=True)
            session = None

    bot = Bot(token=TOKEN, session=session)
    dp = Dispatcher()
    
    # Настройка graceful shutdown
    def signal_handler(signum, frame):
        logging.info(f"Received signal {signum}, shutting down...")
        asyncio.create_task(shutdown(bot, session))
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    await start_scheduler(bot)
    await setup_bot_commands(bot)
    dp.include_router(router)
    
    logger.info("Bot started successfully")
    
    # Бесконечный цикл с перезапуском при падении поллинга
    restart_count = 0
    max_restarts = 10
    while restart_count < max_restarts:
        try:
            await dp.start_polling(bot)
        except KeyboardInterrupt:
            logger.info("Bot stopped by user")
            break
        except Exception as e:
            restart_count += 1
            logger.error(f"Polling crashed (attempt {restart_count}/{max_restarts}): {e}", exc_info=True)
            if restart_count < max_restarts:
                await asyncio.sleep(min(5 * restart_count, 60))  # увеличиваем задержку
            else:
                logger.error("Max restart attempts reached, shutting down")
                break

async def shutdown(bot, session):
    """Graceful shutdown."""
    logging.info("Starting graceful shutdown...")
    
    # Останавливаем бота
    if bot.session:
        await bot.session.close()
    if session:
        await session.close()
    
    # Закрываем движок БД
    await engine.dispose()
    
    logging.info("Shutdown complete.")


if __name__ == "__main__":
    asyncio.run(main())