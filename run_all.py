import asyncio
import logging
import signal
import sys
import io
from pathlib import Path

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiohttp import web
from web.services.auth import PromptService

# === Настройка вывода в UTF-8 ===
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Импорты
from config import TOKEN, PROXY_URL, ADMIN_BOT_TOKEN, settings
from handlers import router as main_router
from handlers.common import setup_bot_commands
from services.scheduler import start_scheduler
from db.base import init_db, engine
from utils.logger import setup_logger
from internal_api import create_internal_app
from web.app import app as fastapi_app
from services.vpn_provider import vpn_provider

# Диспетчер админ-бота (из существующего модуля)
from admin.bot import dp as admin_dp

# Модуль web.routes.web (для установки глобальных переменных вебхуков)
from web.routes import web as web_routes


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

    # VPN аутентификация
    try:
        await vpn_provider.login()
        logger.info("VPN provider authenticated")
    except Exception as e:
        logger.warning(f"VPN pre-auth failed: {e}")

    # --- Настройка основного бота (webhook) ---
    if PROXY_URL:
        main_session = AiohttpSession(proxy=PROXY_URL, timeout=180)
        logger.info(f"Proxy configured: {PROXY_URL}")
    else:
        main_session = AiohttpSession(timeout=180)
        logger.info("No proxy, timeout 180s")

    main_bot = Bot(token=TOKEN, session=main_session)
    main_dp = Dispatcher()
    main_dp.include_router(main_router)

    # Передаём в модуль web.routes.web для обработки вебхука
    web_routes.webhook_bot = main_bot
    web_routes.webhook_dp = main_dp

    # --- Админ-бот (webhook) ---
    admin_bot = None
    if ADMIN_BOT_TOKEN and settings.ADMIN_WEBHOOK_URL:
        admin_bot = Bot(token=ADMIN_BOT_TOKEN, session=AiohttpSession(timeout=180))
        web_routes.webhook_admin_bot = admin_bot
        web_routes.webhook_admin_dp = admin_dp
        await admin_bot.set_webhook(
            url=settings.ADMIN_WEBHOOK_URL,
            secret_token=settings.ADMIN_WEBHOOK_SECRET or None
        )
        logger.info(f"Admin webhook set to {settings.ADMIN_WEBHOOK_URL}")
    else:
        logger.warning("ADMIN_BOT_TOKEN or ADMIN_WEBHOOK_URL not set, admin bot disabled")

    # --- Внутренний HTTP API бота (порт 8001) ---
    internal_app = create_internal_app()
    internal_runner = web.AppRunner(internal_app)
    await internal_runner.setup()
    internal_site = web.TCPSite(internal_runner, 'localhost', 8001)
    await internal_site.start()
    logger.info("Internal API started on http://localhost:8001")

    # --- Запуск FastAPI (порт 8000) ---
    config = uvicorn.Config(app=fastapi_app, host="0.0.0.0", port=8000, log_level="info")
    await PromptService.init_cache()
    server = uvicorn.Server(config)
    web_task = asyncio.create_task(server.serve())
    logger.info("Web server started on http://0.0.0.0:8000")

    # --- Установка вебхука основного бота ---
    webhook_url = settings.WEBHOOK_URL
    if not webhook_url:
        logger.error("WEBHOOK_URL not set in .env")
        sys.exit(1)
    webhook_secret = settings.WEBHOOK_SECRET or None
    await main_bot.set_webhook(url=webhook_url, secret_token=webhook_secret)
    logger.info(f"Main bot webhook set to {webhook_url}")

    # --- Планировщик фоновых задач ---
    await start_scheduler(main_bot)
    await setup_bot_commands(main_bot)

    # --- Graceful shutdown ---
    async def shutdown():
        logger.info("Shutting down…")
        # Удаляем вебхуки
        await main_bot.delete_webhook()
        if admin_bot:
            await admin_bot.delete_webhook()
            await admin_bot.session.close()
        await main_bot.session.close()
        await vpn_provider.close()
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

    # Бесконечное ожидание (завершится по сигналу)
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())