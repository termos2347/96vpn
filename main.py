import asyncio
import logging
import signal
import sys
from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiohttp import ClientTimeout, TCPConnector, ClientSession, web
from config import TOKEN, PROXY_URL
from handlers import router
from handlers.common import setup_bot_commands
from services.scheduler import start_scheduler
from db.base import init_db, engine
from utils.logger import setup_logger
from internal_api import create_internal_app

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
        connector = TCPConnector(
            limit=100,
            limit_per_host=30,
            ttl_dns_cache=600,           # увеличили кэш DNS
            force_close=False,
            enable_cleanup_closed=True,
            keepalive_timeout=30,        # держим соединение дольше
        )
        timeout = ClientTimeout(
            total=180,                   # общий таймаут 3 минуты
            connect=30,                  # таймаут подключения
            sock_read=60,                # чтения данных
            sock_connect=30,             # соединения сокета
        )
        client_session = ClientSession(connector=connector, timeout=timeout)
        session = AiohttpSession(proxy=PROXY_URL)
        session._session = client_session
        logger.info(f"Proxy configured: {PROXY_URL} with extended timeouts")

    bot = Bot(token=TOKEN, session=session)
    dp = Dispatcher()

    # Запускаем внутренний HTTP API
    internal_app = create_internal_app()
    runner = web.AppRunner(internal_app)
    await runner.setup()
    site = web.TCPSite(runner, 'localhost', 8001)
    await site.start()
    logger.info("Internal API started on http://localhost:8001")

    # Обработчик graceful shutdown (работает в Windows)
    loop = asyncio.get_running_loop()

    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        # Планируем задачу остановки
        asyncio.create_task(shutdown(bot, session, runner))

    # Регистрируем обработчики сигналов (работает в Windows)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    await start_scheduler(bot)
    await setup_bot_commands(bot)
    dp.include_router(router)

    logger.info("Bot started successfully")

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
                await asyncio.sleep(min(5 * restart_count, 60))
            else:
                logger.error("Max restart attempts reached, shutting down")
                break


async def shutdown(bot, session, internal_runner=None):
    """Graceful shutdown."""
    logging.info("Starting graceful shutdown...")

    if bot.session:
        await bot.session.close()
    if session:
        await session.close()

    if internal_runner:
        await internal_runner.cleanup()

    await engine.dispose()
    logging.info("Shutdown complete.")


if __name__ == "__main__":
    asyncio.run(main())