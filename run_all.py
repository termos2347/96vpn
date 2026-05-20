import asyncio
import logging
import signal
import sys
import io
from pathlib import Path

# Устанавливаем кодировку stdout
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Настраиваем логгер ПЕРВЫМ делом
from utils.logger import setup_logger
setup_logger()

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiohttp import web

from db.migrate import run_migrations
from web.services.auth import PromptService

from config import TOKEN, PROXY_URL, ADMIN_BOT_TOKEN, settings
from handlers import router as main_router, set_server_pool, set_vpn_manager
from handlers.common import setup_bot_commands
from services.scheduler import start_scheduler
from services.server_pool import ServerPool
from services.vpn_manager import VPNManager
from db.base import init_db, engine
from internal_api import create_internal_app
from web.app import app as fastapi_app
from services.vpn_provider import vpn_provider
from admin import startup as admin_startup, shutdown as admin_shutdown, dp as admin_dp
from web.routes import web as web_routes
import sentry_sdk

logger = logging.getLogger(__name__)

if settings.SENTRY_DSN:
    sentry_sdk.init(dsn=settings.SENTRY_DSN, traces_sample_rate=0.1,
                    environment="production" if not settings.DEBUG else "development",
                    release="1.0.0")
    logger.info("Sentry initialized for bot")

def validate_webhook_url(url: str, bot_name: str = "main") -> bool:
    """Проверяет корректность URL вебхука."""
    if not url:
        logger.error(f"{bot_name} WEBHOOK_URL is empty! Bot will not receive updates.")
        return False
    if not url.startswith(("http://", "https://")):
        logger.error(f"{bot_name} WEBHOOK_URL invalid scheme: {url}")
        return False
    if not url.startswith("https://"):
        logger.warning(f"{bot_name} WEBHOOK_URL should use HTTPS: {url}")
    return True

async def _login_all_servers(server_pool: ServerPool):
    """Фоновая авторизация на всех серверах."""
    await asyncio.sleep(2)
    for provider in server_pool.providers.values():
        try:
            await provider.login()
            logger.debug("Logged in to server provider")
        except Exception as e:
            logger.warning(f"Failed to login to some server: {e}")

async def main():
    logger.info("Starting combined server (bot + web)...")
    stop_event = asyncio.Event()

    # Валидация WEBHOOK_URL
    if not validate_webhook_url(settings.WEBHOOK_URL, "main"):
        sys.exit(1)
    if settings.ADMIN_WEBHOOK_URL and not validate_webhook_url(settings.ADMIN_WEBHOOK_URL, "admin"):
        sys.exit(1)

    try:
        logger.info("Initializing database...")
        await init_db()
        await run_migrations()
        logger.info("Database initialized")
    except Exception as e:
        logger.error(f"Database init failed: {e}", exc_info=True)
        sys.exit(1)

    # Инициализация пула VPN-серверов
    server_pool = ServerPool()
    await server_pool.refresh_servers()
    set_server_pool(server_pool)
    logger.info("VPN server pool initialized")

    vpn_manager = VPNManager(server_pool)
    set_vpn_manager(vpn_manager)

    asyncio.create_task(_login_all_servers(server_pool))

    await admin_startup()

    # Настройка сессии бота с прокси (без костылей)
    if PROXY_URL:
        main_session = AiohttpSession(proxy=PROXY_URL, timeout=180)
        logger.info(f"Proxy configured: {PROXY_URL} with timeout 180s")
    else:
        main_session = AiohttpSession(timeout=180)
        logger.info("No proxy, timeout 180s")

    main_bot = Bot(token=TOKEN, session=main_session)
    main_dp = Dispatcher()
    main_dp.include_router(main_router)

    web_routes.webhook_bot = main_bot
    web_routes.webhook_dp = main_dp

    from admin import bot as admin_module
    admin_bot_instance = admin_module.admin_bot
    if ADMIN_BOT_TOKEN and settings.ADMIN_WEBHOOK_URL:
        web_routes.webhook_admin_bot = admin_bot_instance
        web_routes.webhook_admin_dp = admin_dp
        await admin_bot_instance.set_webhook(
            url=settings.ADMIN_WEBHOOK_URL,
            secret_token=settings.ADMIN_WEBHOOK_SECRET or None
        )
        logger.info(f"Admin webhook set to {settings.ADMIN_WEBHOOK_URL}")
    else:
        logger.warning("Admin webhook not configured")

    # Внутренний API
    internal_app = create_internal_app()
    internal_runner = web.AppRunner(internal_app)
    await internal_runner.setup()
    internal_site = web.TCPSite(internal_runner, settings.INTERNAL_API_HOST, settings.INTERNAL_API_PORT)
    await internal_site.start()
    logger.info(f"Internal API started on http://{settings.INTERNAL_API_HOST}:{settings.INTERNAL_API_PORT}")

    # Веб-сервер FastAPI
    config = uvicorn.Config(app=fastapi_app, host="0.0.0.0", port=8000, log_level="info")
    await PromptService.init_cache()
    server = uvicorn.Server(config)
    web_task = asyncio.create_task(server.serve())
    logger.info("Web server started on http://0.0.0.0:8000")

    # Установка вебхука основного бота
    webhook_url = settings.WEBHOOK_URL
    if not webhook_url:
        logger.error("WEBHOOK_URL not set in .env")
        sys.exit(1)
    await main_bot.set_webhook(
        url=webhook_url,
        secret_token=settings.WEBHOOK_SECRET or None
    )
    logger.info(f"Main bot webhook set to {webhook_url}")

    await start_scheduler(main_bot)

    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, shutting down…")
        asyncio.create_task(shutdown(main_bot, admin_bot_instance, internal_runner, server, web_task, server_pool, stop_event))

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    logger.info("All services started. Waiting for stop signal...")
    await stop_event.wait()

async def shutdown(main_bot, admin_bot_instance, internal_runner, server, web_task, server_pool, stop_event):
    logger.info("Shutting down…")
    await main_bot.delete_webhook()
    if admin_bot_instance:
        await admin_bot_instance.delete_webhook()
        await admin_bot_instance.session.close()
    await main_bot.session.close()
    await admin_shutdown()
    await server_pool.close_all()
    await vpn_provider.close()
    server.should_exit = True
    await web_task
    await internal_runner.cleanup()
    await engine.dispose()
    logger.info("Shutdown complete.")
    stop_event.set()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutdown by user")
    except Exception as e:
        logger.exception("Fatal error in main")
        sys.exit(1)