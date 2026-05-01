import asyncio
import logging
import signal
import sys
import io
from pathlib import Path

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiohttp import ClientTimeout, TCPConnector, ClientSession, web

# Импорты бота
from config import TOKEN, PROXY_URL
from handlers import router
from handlers.common import setup_bot_commands
from services.scheduler import start_scheduler
from db.base import init_db, engine
from utils.logger import setup_logger
from internal_api import create_internal_app

# Импорты веб-части
from web.app import app as fastapi_app

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

async def main():
    # Логирование
    setup_logger()
    logger = logging.getLogger(__name__)
    logger.info("Starting combined server (bot + web)…")

    # Инициализация БД
    try:
        await init_db()
        logger.info("Database initialized")
    except Exception as e:
        logger.error(f"Database init failed: {e}")
        sys.exit(1)

    # === Настройка бота ===
    session = None
    if PROXY_URL:
        try:
            connector = TCPConnector(
                limit=100, limit_per_host=30, ttl_dns_cache=300,
                force_close=False, enable_cleanup_closed=True,
            )
            timeout = ClientTimeout(total=60, connect=20, sock_read=30, sock_connect=20)
            client_session = ClientSession(connector=connector, timeout=timeout)
            session = AiohttpSession(proxy=PROXY_URL)
            session._session = client_session
            logger.info(f"Proxy configured: {PROXY_URL}")
        except Exception as e:
            logger.error(f"Proxy setup error: {e}")
            session = None

    bot = Bot(token=TOKEN, session=session)
    dp = Dispatcher()
    dp.include_router(router)

    # === Внутренний HTTP API бота (для активации) ===
    internal_app = create_internal_app()
    internal_runner = web.AppRunner(internal_app)
    await internal_runner.setup()
    internal_site = web.TCPSite(internal_runner, 'localhost', 8001)
    await internal_site.start()
    logger.info("Internal API started on http://localhost:8001")

    # === Запуск FastAPI через uvicorn (в asyncio) ===
    config = uvicorn.Config(
        app=fastapi_app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
    )
    server = uvicorn.Server(config)
    # Запускаем его как фоновую задачу
    web_task = asyncio.create_task(server.serve())
    logger.info("Web server started on http://0.0.0.0:8000")

    # === Graceful shutdown ===
    loop = asyncio.get_running_loop()

    def shutdown_handler(signum, frame):
        logger.info(f"Signal {signum} received, shutting down…")
        # Отменяем все задачи (бот и веб)
        for task in asyncio.all_tasks(loop):
            task.cancel()

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    # === Запуск бота ===
    await start_scheduler(bot)
    await setup_bot_commands(bot)

    logger.info("Bot starting polling…")
    restart_count = 0
    max_restarts = 10
    while restart_count < max_restarts:
        try:
            await dp.start_polling(bot)
        except asyncio.CancelledError:
            logger.info("Polling cancelled")
            break
        except Exception as e:
            restart_count += 1
            logger.error(f"Polling error ({restart_count}/{max_restarts}): {e}")
            if restart_count < max_restarts:
                await asyncio.sleep(min(5 * restart_count, 60))
            else:
                logger.error("Max restarts reached")
                break

    # === Остановка веб-сервера и API ===
    logger.info("Shutting down web server…")
    server.should_exit = True
    await web_task

    await internal_runner.cleanup()
    await engine.dispose()
    logger.info("Shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())