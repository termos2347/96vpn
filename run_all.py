import asyncio
import logging
import signal
import sys
from pathlib import Path

# Устанавливаем кодировку для Windows
sys.stdout = open(sys.stdout.fileno(), 'w', encoding='utf-8')
sys.stderr = open(sys.stderr.fileno(), 'w', encoding='utf-8')

from utils.logger import setup_logger
setup_logger()

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession

from config import TOKEN, PROXY_URL, ADMIN_BOT_TOKEN, settings
from handlers import router as main_router, set_server_pool, set_vpn_manager
from handlers.common import setup_bot_commands
from services.scheduler import start_scheduler
from services.server_pool import ServerPool
from services.vpn_manager import VPNManager
from db.base import init_db, engine
from internal_api import create_internal_app, set_main_bot, set_main_dp, set_admin_bot, set_admin_dp
from admin.bot import startup as admin_startup, shutdown as admin_shutdown, dp as admin_dp, admin_bot as admin_bot_instance
import sentry_sdk

logger = logging.getLogger(__name__)

if settings.SENTRY_DSN:
    sentry_sdk.init(dsn=settings.SENTRY_DSN, traces_sample_rate=0.1)

# ------------------------------------------------------------------
# Фоновая авторизация на всех VPN‑серверах
# ------------------------------------------------------------------
async def _login_all_servers(server_pool: ServerPool):
    await asyncio.sleep(2)
    for provider in server_pool.providers.values():
        try:
            await provider.login()
            logger.debug("Logged in to server provider")
        except Exception as e:
            logger.warning(f"Failed to login to some server: {e}")

# ------------------------------------------------------------------
# Главная функция
# ------------------------------------------------------------------
async def main():
    logger.info("Starting VPN bot with internal API (webhooks)")

    # Инициализация базы данных (без миграций Alembic)
    try:
        await init_db()
        logger.info("Database initialized")
    except Exception as e:
        logger.error(f"Database init failed: {e}", exc_info=True)
        sys.exit(1)

    # Пул VPN‑серверов
    server_pool = ServerPool()
    await server_pool.refresh_servers()
    set_server_pool(server_pool)
    logger.info("VPN server pool initialized")

    vpn_manager = VPNManager(server_pool)
    set_vpn_manager(vpn_manager)
    asyncio.create_task(_login_all_servers(server_pool))

    # Запуск админ-бота (создаются экземпляры Bot и Dispatcher)
    await admin_startup()
    # admin_bot_instance и admin_dp уже импортированы из admin.bot

    # Настройка сессии основного бота (с поддержкой прокси)
    if PROXY_URL:
        main_session = AiohttpSession(proxy=PROXY_URL, timeout=180)
        logger.info(f"Proxy configured: {PROXY_URL}")
    else:
        main_session = AiohttpSession(timeout=180)

    main_bot = Bot(token=TOKEN, session=main_session)
    main_dp = Dispatcher()
    main_dp.include_router(main_router)
    await setup_bot_commands(main_bot)

    # Передаём ботов и диспетчеры во внутреннее API (для вебхуков)
    from internal_api import (
        set_main_bot, set_main_dp, set_admin_bot, set_admin_dp
    )
    set_main_bot(main_bot)
    set_main_dp(main_dp)
    set_admin_bot(admin_bot_instance)
    set_admin_dp(admin_dp)

    # Запуск внутреннего API (aiohttp) на порту 8001
    internal_app = create_internal_app()
    internal_runner = web.AppRunner(internal_app)
    await internal_runner.setup()
    internal_site = web.TCPSite(
        internal_runner,
        settings.INTERNAL_API_HOST,
        settings.INTERNAL_API_PORT
    )
    await internal_site.start()
    logger.info(f"Internal API started on http://{settings.INTERNAL_API_HOST}:{settings.INTERNAL_API_PORT}")

    # Установка вебхуков для ботов (если URL заданы)
    if settings.WEBHOOK_URL:
        await main_bot.set_webhook(
            url=settings.WEBHOOK_URL,
            secret_token=settings.WEBHOOK_SECRET or None
        )
        logger.info(f"Main bot webhook set to {settings.WEBHOOK_URL}")
    else:
        logger.warning("WEBHOOK_URL not set, main bot will not receive updates")

    if settings.ADMIN_WEBHOOK_URL and ADMIN_BOT_TOKEN and admin_bot_instance:
        await admin_bot_instance.set_webhook(
            url=settings.ADMIN_WEBHOOK_URL,
            secret_token=settings.ADMIN_WEBHOOK_SECRET or None
        )
        logger.info(f"Admin bot webhook set to {settings.ADMIN_WEBHOOK_URL}")
    else:
        logger.warning("Admin bot webhook not configured")

    # Запуск фоновых задач (проверка истёкших подписок, напоминания)
    await start_scheduler(main_bot)

    # Ожидание сигнала завершения (graceful shutdown)
    stop_event = asyncio.Event()

    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        asyncio.create_task(shutdown(main_bot, admin_bot_instance, internal_runner, server_pool, stop_event))

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    logger.info("All services started. Waiting for stop signal...")
    await stop_event.wait()

# ------------------------------------------------------------------
# Graceful shutdown
# ------------------------------------------------------------------
async def shutdown(main_bot, admin_bot_instance, internal_runner, server_pool, stop_event):
    logger.info("Shutting down...")
    # Снимаем вебхуки
    await main_bot.delete_webhook()
    if admin_bot_instance:
        await admin_bot_instance.delete_webhook()
        await admin_bot_instance.session.close()
    await main_bot.session.close()
    # Останавливаем админ-бота
    from admin.bot import shutdown as admin_shutdown
    await admin_shutdown()
    # Закрываем подключения к VPN-серверам
    await server_pool.close_all()
    # Останавливаем внутреннее API
    await internal_runner.cleanup()
    # Закрываем соединение с БД
    from db.base import engine
    await engine.dispose()
    logger.info("Shutdown complete.")
    stop_event.set()

# ------------------------------------------------------------------
# Точка входа
# ------------------------------------------------------------------
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutdown by user")
    except Exception as e:
        logger.exception("Fatal error in main")
        sys.exit(1)