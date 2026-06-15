import asyncio
import logging
import signal
import sys
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession

from config import TOKEN, PROXY_URL, ADMIN_BOT_TOKEN, settings
from handlers import router as main_router
from handlers.common import setup_bot_commands
from services.scheduler import start_scheduler
from services.server_pool import ServerPool
from services.vpn_manager import VPNManager
from db.migrate import run_migrations
from db.base import engine
from internal_api import create_internal_app, set_main_bot, set_main_dp, set_admin_bot, set_admin_dp
import admin.bot
from utils.logger import setup_logger

setup_logger()
logger = logging.getLogger(__name__)

# Глобальные объекты
main_bot = None
main_dp = None
internal_runner = None

async def on_startup():
    global main_bot, main_dp, internal_runner
    logger.info("Starting VPN bot with webhooks...")

    # 1. Инициализация БД
    await run_migrations()
    logger.info("Database migrations applied")

    # 2. Пул серверов и VPN менеджер
    server_pool = ServerPool()
    await server_pool.refresh_servers()
    from handlers import set_server_pool, set_vpn_manager
    set_server_pool(server_pool)
    set_vpn_manager(VPNManager(server_pool))

    # 3. Запуск админ-бота (инициализирует admin.bot.admin_bot и admin.bot.dp)
    await admin.bot.startup()

    # 4. Основной бот (с поддержкой прокси)
    if PROXY_URL:
        main_session = AiohttpSession(proxy=PROXY_URL, timeout=180)
        logger.info(f"Proxy configured: {PROXY_URL}")
    else:
        main_session = AiohttpSession(timeout=180)

    main_bot = Bot(token=TOKEN, session=main_session)
    main_dp = Dispatcher()
    main_dp.include_router(main_router)
    await setup_bot_commands(main_bot)

    # 5. Передаём экземпляры во внутреннее API (для вебхуков)
    set_main_bot(main_bot)
    set_main_dp(main_dp)
    set_admin_bot(admin.bot.admin_bot)
    set_admin_dp(admin.bot.dp)

    # 6. Запуск внутреннего API (aiohttp) – будет слушать вебхуки
    internal_app = create_internal_app()
    internal_runner = web.AppRunner(internal_app)
    await internal_runner.setup()
    site = web.TCPSite(internal_runner, settings.INTERNAL_API_HOST, settings.INTERNAL_API_PORT)
    await site.start()
    logger.info(f"Internal API started on http://{settings.INTERNAL_API_HOST}:{settings.INTERNAL_API_PORT}")

    # 7. Установка вебхуков (только если заданы URL в .env)
    webhook_url = getattr(settings, 'WEBHOOK_URL', None)
    admin_webhook_url = getattr(settings, 'ADMIN_WEBHOOK_URL', None)
    if webhook_url:
        await main_bot.set_webhook(url=webhook_url, secret_token=settings.WEBHOOK_SECRET)
        logger.info(f"Main bot webhook set to {webhook_url}")
    else:
        logger.warning("WEBHOOK_URL not set, main bot webhook not configured")

    if admin_webhook_url and admin.bot.admin_bot:
        await admin.bot.admin_bot.set_webhook(url=admin_webhook_url, secret_token=settings.ADMIN_WEBHOOK_SECRET)
        logger.info(f"Admin bot webhook set to {admin_webhook_url}")
    else:
        logger.warning("Admin bot webhook not configured")

    # 8. Запуск фоновых задач
    await start_scheduler(main_bot)

    logger.info("All services started. Waiting for webhook requests...")

async def on_shutdown():
    logger.info("Shutting down...")
    if main_bot:
        try:
            await main_bot.delete_webhook()
        except Exception:
            pass
        await main_bot.session.close()
    if admin.bot.admin_bot:
        try:
            await admin.bot.admin_bot.delete_webhook()
        except Exception:
            pass
        await admin.bot.admin_bot.session.close()
    await admin.bot.shutdown()
    if internal_runner:
        await internal_runner.cleanup()
    if engine:
        await engine.dispose()
    else:
        logger.warning("Database engine not initialized, skipping dispose")
    logger.info("Shutdown complete.")

async def main():
    await on_startup()
    stop_event = asyncio.Event()
    def signal_handler():
        stop_event.set()
    # Регистрируем обработчики сигналов (только для Unix)
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGINT, signal_handler)
    loop.add_signal_handler(signal.SIGTERM, signal_handler)
    await stop_event.wait()
    await on_shutdown()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutdown by user")
    except Exception as e:
        logger.exception("Fatal error")
        sys.exit(1)