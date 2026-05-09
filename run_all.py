import asyncio
import logging
import signal
import sys
import io
from pathlib import Path

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramNetworkError
from aiohttp import web
from web.services.auth import PromptService

# === Настройка вывода в UTF-8 ===
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Импорты бота
from config import TOKEN, PROXY_URL, ADMIN_BOT_TOKEN
from handlers import router
from handlers.common import setup_bot_commands
from services.scheduler import start_scheduler
from db.base import init_db, engine
from utils.logger import setup_logger
from internal_api import create_internal_app

# Импорты веб-части
from web.app import app as fastapi_app

# Глобальный провайдер VPN
from services.vpn_provider import vpn_provider

# Админ-бот
from admin import start_polling as start_admin_polling, shutdown as shutdown_admin_bot


async def main():
    setup_logger()
    logger = logging.getLogger(__name__)
    logger.info("Starting combined server (bot + web)…")

    # Инициализация БД (асинхронная)
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

    # --- Настройка бота с увеличенным таймаутом ---
    # Aiogram 3.x: timeout передаётся как число секунд
    if PROXY_URL:
        session = AiohttpSession(proxy=PROXY_URL, timeout=180)
        logger.info(f"Proxy configured: {PROXY_URL} with timeout 180s")
    else:
        session = AiohttpSession(timeout=180)
        logger.info("No proxy, using extended timeout 180s")

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

    # --- Запуск админ-бота (если настроен) ---
    if ADMIN_BOT_TOKEN:
        admin_task = asyncio.create_task(start_admin_polling())
        logger.info("Admin bot polling started")
    else:
        logger.warning("ADMIN_BOT_TOKEN not set, admin bot disabled")

    # --- Graceful shutdown ---
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

    # Цикл с переподключением при сетевых ошибках
    restart_count = 0
    max_restarts = 20
    while restart_count < max_restarts:
        try:
            logger.info("Bot starting polling…")
            await dp.start_polling(bot)
        except asyncio.CancelledError:
            logger.info("Polling cancelled")
            break
        except TelegramNetworkError as e:
            logger.warning(f"Network error (likely disconnect): {e}")
            await asyncio.sleep(2)
            # Не увеличиваем restart_count для сетевых проблем
            continue
        except Exception as e:
            restart_count += 1
            logger.error(f"Polling error ({restart_count}/{max_restarts}): {e}", exc_info=True)
            if restart_count < max_restarts:
                await asyncio.sleep(min(5 * restart_count, 60))
            else:
                logger.error("Max restarts reached, stopping bot")
                break
    await shutdown()


if __name__ == "__main__":
    asyncio.run(main())