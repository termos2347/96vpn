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
from web.services.auth import PromptService

# === Настройка вывода в UTF-8 (избавляет от ошибок с эмодзи) ===
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Импорты бота
from config import TOKEN, PROXY_URL, ADMIN_BOT_TOKEN, settings
from handlers import router
from handlers.common import setup_bot_commands
from services.scheduler import start_scheduler
from db.base import init_db, engine
from utils.logger import setup_logger
from internal_api import create_internal_app

# Импорты веб-части
from web.app import app as fastapi_app

# Глобальный провайдер VPN (используется и в боте, и в вебе)
from services.vpn_provider import vpn_provider

# Админ-бот
from admin import start_polling as start_admin_polling, shutdown as shutdown_admin_bot

async def main():
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

    # Предварительная аутентификация с VPN‑панелью
    try:
        await vpn_provider.login()
        logger.info("VPN provider authenticated")
    except Exception as e:
        logger.warning(f"VPN provider pre-auth failed (will retry later): {e}")

    # --- Настройка бота ---
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

    # --- Внутренний HTTP API бота (порт 8001) ---
    internal_app = create_internal_app()
    internal_runner = web.AppRunner(internal_app)
    await internal_runner.setup()
    internal_site = web.TCPSite(internal_runner, 'localhost', 8001)
    await internal_site.start()
    logger.info("Internal API started on http://localhost:8001")

    # --- Запуск FastAPI через uvicorn ---
    config = uvicorn.Config(
        app=fastapi_app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
    )
    
    await PromptService.init_cache()
    server = uvicorn.Server(config)
    web_task = asyncio.create_task(server.serve())
    logger.info("Web server started on http://0.0.0.0:8000")

    # --- Запуск админ-бота ---
    if ADMIN_BOT_TOKEN:
        admin_task = asyncio.create_task(start_admin_polling())
        logger.info("Admin bot polling started")
    else:
        logger.warning("ADMIN_BOT_TOKEN not set, admin bot disabled")

    # --- Graceful shutdown ---
    loop = asyncio.get_running_loop()

    async def shutdown():
        """Корректное завершение всех сервисов."""
        logger.info("Shutting down…")
        try:
            await dp.stop_polling()
        except Exception:
            pass

        if bot.session:
            await bot.session.close()
        if session:
            await session.close()

        await vpn_provider.close()

        # Остановка админ-бота
        if ADMIN_BOT_TOKEN:
            await shutdown_admin_bot()

        server.should_exit = True
        await web_task

        await internal_runner.cleanup()
        await engine.dispose()
        logger.info("Shutdown complete.")

    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, exiting…")
        asyncio.create_task(shutdown())

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # --- Запуск планировщика и бота ---
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

    await shutdown()

if __name__ == "__main__":
    asyncio.run(main())