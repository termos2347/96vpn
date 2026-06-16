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
_shutting_down = False  # флаг для предотвращения повторного вызова shutdown

async def on_startup():
    global main_bot, main_dp, internal_runner
    logger.info("Starting VPN bot with webhooks...")

    # 1. Инициализация БД (в DEBUG режиме пропускается)
    if not settings.DEBUG:
        await run_migrations()
    else:
        logger.info("DEBUG mode: skipping automatic migrations")
    logger.info("Database ready")

    # 2. Пул серверов и VPN менеджер
    server_pool = ServerPool()
    await server_pool.refresh_servers()
    from handlers import set_server_pool, set_vpn_manager
    set_server_pool(server_pool)
    set_vpn_manager(VPNManager(server_pool))

    # 3. Запуск админ-бота
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

    # Передаём экземпляры во внутреннее API (для вебхуков)
    set_main_bot(main_bot)
    set_main_dp(main_dp)
    set_admin_bot(admin.bot.admin_bot)
    set_admin_dp(admin.bot.dp)

    # 5. Запуск внутреннего API с reuse_address
    internal_app = create_internal_app()
    internal_runner = web.AppRunner(internal_app)
    await internal_runner.setup()
    site = web.TCPSite(
        internal_runner,
        host=settings.INTERNAL_API_HOST,
        port=settings.INTERNAL_API_PORT,
        reuse_address=True   # позволяет переиспользовать порт после аварийного завершения
    )
    await site.start()
    logger.info(f"Internal API started on http://{settings.INTERNAL_API_HOST}:{settings.INTERNAL_API_PORT}")

    # 6. Установка вебхуков (только если заданы URL в .env)
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

    # 7. Запуск фоновых задач
    await start_scheduler(main_bot)

    logger.info("All services started. Waiting for webhook requests...")

async def on_shutdown():
    global _shutting_down
    if _shutting_down:
        logger.info("Shutdown already in progress, skipping")
        return
    _shutting_down = True

    logger.info("Shutting down...")
    
    # Закрываем вебхуки и сессии ботов
    if main_bot:
        try:
            await main_bot.delete_webhook()
        except Exception as e:
            logger.debug(f"Error deleting main webhook: {e}")
        try:
            await main_bot.session.close()
        except Exception as e:
            logger.debug(f"Error closing main bot session: {e}")
    
    if admin.bot.admin_bot:
        try:
            await admin.bot.admin_bot.delete_webhook()
        except Exception as e:
            logger.debug(f"Error deleting admin webhook: {e}")
        try:
            await admin.bot.admin_bot.session.close()
        except Exception as e:
            logger.debug(f"Error closing admin bot session: {e}")
    
    await admin.bot.shutdown()
    
    # Закрываем внутреннее API
    if internal_runner:
        try:
            await internal_runner.cleanup()
            logger.info("Internal API cleaned up")
        except Exception as e:
            logger.error(f"Error cleaning internal API: {e}")
    
    # Закрываем соединения с БД
    if engine:
        try:
            await engine.dispose()
            logger.info("Database engine disposed")
        except Exception as e:
            logger.error(f"Error disposing engine: {e}")
    else:
        logger.warning("Database engine not initialized, skipping dispose")
    
    logger.info("Shutdown complete.")

async def shutdown_with_timeout():
    """Завершает работу с таймаутом, чтобы не зависнуть."""
    try:
        await asyncio.wait_for(on_shutdown(), timeout=10.0)
    except asyncio.TimeoutError:
        logger.error("Shutdown timed out after 10 seconds, forcing exit")
    except Exception as e:
        logger.exception(f"Unexpected error during shutdown: {e}")

async def main():
    # Запускаем стартовую инициализацию
    await on_startup()
    
    # Создаём событие для ожидания сигнала остановки
    stop_event = asyncio.Event()
    
    def signal_handler():
        logger.info("Received stop signal, initiating graceful shutdown...")
        stop_event.set()
    
    # Получаем цикл событий и устанавливаем обработчики сигналов
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)
    
    try:
        # Ждём сигнал остановки
        await stop_event.wait()
    except asyncio.CancelledError:
        logger.info("Main task cancelled")
    finally:
        # Выполняем завершение с таймаутом
        await shutdown_with_timeout()
        # Даём время на освобождение порта (для сокетов в TIME_WAIT)
        await asyncio.sleep(0.5)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutdown by user (KeyboardInterrupt)")
    except Exception as e:
        logger.exception("Fatal error")
        sys.exit(1)