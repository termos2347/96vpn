import asyncio
import logging
import signal
import sys
import io
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
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
    sentry_sdk.init(dsn=settings.SENTRY_DSN, traces_sample_rate=0.1, environment="production" if not settings.DEBUG else "development", release="1.0.0")
    logger.info("Sentry initialized for bot")

async def main():
    logger.info("Starting combined server (bot + web)…")

    try:
        await init_db()
        await run_migrations()
        logger.info("Database initialized")
    except Exception as e:
        logger.error(f"Database init failed: {e}")
        sys.exit(1)

    server_pool = ServerPool()
    await server_pool.refresh_servers()
    set_server_pool(server_pool)
    logger.info("VPN server pool initialized")

    vpn_manager = VPNManager(server_pool)
    set_vpn_manager(vpn_manager)

    asyncio.create_task(_login_all_servers(server_pool))

    await admin_startup()

    if PROXY_URL:
        main_session = AiohttpSession(proxy=PROXY_URL, timeout=180)
        logger.info(f"Proxy configured: {PROXY_URL}")
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

    internal_app = create_internal_app()
    internal_runner = web.AppRunner(internal_app)
    await internal_runner.setup()
    internal_site = web.TCPSite(internal_runner, '0.0.0.0', 8001)
    await internal_site.start()
    logger.info("Internal API started on 0.0.0.0:8001")

    config = uvicorn.Config(app=fastapi_app, host="0.0.0.0", port=8000, log_level="info")
    await PromptService.init_cache()
    server = uvicorn.Server(config)
    web_task = asyncio.create_task(server.serve())
    logger.info("Web server started on http://0.0.0.0:8000")

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

    stop_event = asyncio.Event()

    async def shutdown():
        logger.info("Shutting down…")
        await main_bot.delete_webhook()
        if admin_bot_instance:
            await admin_bot_instance.delete_webhook()
            await admin_bot_instance.session.close()
        await main_bot.session.close()
        await admin_shutdown()
        await server_pool.close_all()
        await vpn_provider.close()          # <-- закрываем сессию провайдера
        server.should_exit = True
        await web_task