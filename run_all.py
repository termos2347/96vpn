import asyncio
import logging
import signal
import sys
import traceback
from aiohttp import web
from aiogram import Bot, Dispatcher

from config import TOKEN, settings
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

# Попытка импорта pyfiglet для ASCII-арта
try:
    from pyfiglet import Figlet
    HAS_PYFIGLET = True
except ImportError:
    HAS_PYFIGLET = False

setup_logger()
logger = logging.getLogger(__name__)

# Глобальные объекты
main_bot = None
main_dp = None
internal_runner = None
_shutting_down = False
_background_tasks = []   # здесь будут только фоновые задачи (scheduler)

async def on_startup():
    global main_bot, main_dp, internal_runner, _background_tasks
    logger.info("=" * 50)
    logger.info("🚀 Starting VPN bot with webhooks...")
    logger.info("=" * 50)

    try:
        # 1. Инициализация БД
        if settings.RUN_MIGRATIONS:
            logger.info("Step 1/7: Running database migrations...")
            await run_migrations()
        else:
            logger.info("Step 1/7: Skipping migrations (RUN_MIGRATIONS=false)")
        logger.info("✅ Database ready")

        # 2. Пул серверов и VPN-менеджер
        logger.info("Step 2/7: Initializing ServerPool and VPNManager...")
        server_pool = ServerPool()
        await server_pool.refresh_servers()
        logger.info("   Servers loaded: %d active", len(server_pool.servers))
        from handlers import set_server_pool, set_vpn_manager
        set_server_pool(server_pool)
        set_vpn_manager(VPNManager(server_pool))
        logger.info("✅ ServerPool and VPNManager ready")

        # 3. Запуск админ-бота
        logger.info("Step 3/7: Starting admin bot...")
        await admin.bot.startup()
        logger.info("✅ Admin bot started")

        # 4. Основной бот
        logger.info("Step 4/7: Initializing main bot...")
        main_bot = Bot(token=TOKEN)
        main_dp = Dispatcher()
        main_dp.include_router(main_router)
        await setup_bot_commands(main_bot)
        logger.info("✅ Main bot initialized")

        # Передаём экземпляры во внутреннее API
        set_main_bot(main_bot)
        set_main_dp(main_dp)
        set_admin_bot(admin.bot.admin_bot)
        set_admin_dp(admin.bot.dp)
        logger.info("   Internal API hooks set")

        # 5. Внутренний API сервер
        logger.info("Step 5/7: Starting internal API server...")
        internal_app = create_internal_app()
        internal_runner = web.AppRunner(internal_app)
        await internal_runner.setup()
        site = web.TCPSite(
            internal_runner,
            host=settings.INTERNAL_API_HOST,
            port=settings.INTERNAL_API_PORT,
            reuse_address=True
        )
        await site.start()
        logger.info(f"✅ Internal API started on http://{settings.INTERNAL_API_HOST}:{settings.INTERNAL_API_PORT}")

        # 6. Установка вебхуков (строго обязательны)
        logger.info("Step 6/7: Setting up webhooks...")

        # Проверка, что URL заданы
        if not settings.WEBHOOK_URL:
            raise ValueError("WEBHOOK_URL is required for webhook mode")
        if not settings.ADMIN_WEBHOOK_URL:
            raise ValueError("ADMIN_WEBHOOK_URL is required for webhook mode")

        # Удаляем старые вебхуки (на случай, если бот перезапущен)
        try:
            await main_bot.delete_webhook()
        except Exception as e:
            logger.debug(f"Could not delete main webhook: {e}")
        try:
            await admin.bot.admin_bot.delete_webhook()
        except Exception as e:
            logger.debug(f"Could not delete admin webhook: {e}")

        # Устанавливаем новые
        await main_bot.set_webhook(
            url=settings.WEBHOOK_URL,
            secret_token=settings.WEBHOOK_SECRET
        )
        logger.info(f"✅ Main bot webhook set to {settings.WEBHOOK_URL}")

        await admin.bot.admin_bot.set_webhook(
            url=settings.ADMIN_WEBHOOK_URL,
            secret_token=settings.ADMIN_WEBHOOK_SECRET
        )
        logger.info(f"✅ Admin bot webhook set to {settings.ADMIN_WEBHOOK_URL}")

        logger.info("✅ Webhooks configured")

        # 7. Запуск фоновых задач (scheduler)
        logger.info("Step 7/7: Starting background tasks...")
        _background_tasks = await start_scheduler(main_bot)
        logger.info("✅ Background tasks started")

        # --- Финиш: вывод ASCII-арта ---
        print("\n" + "=" * 50)
        print("🎉 ALL SERVICES STARTED SUCCESSFULLY! 🎉")
        print("=" * 50)

        if HAS_PYFIGLET:
            try:
                f = Figlet(font='slant')
                ascii_art = f.renderText('96VPN BOT')
                print("\n" + ascii_art)
            except Exception:
                print("(ASCII art not available)")
        else:
            print("""
             ╔══╗ ╔╗   ╔╗╔╗   ╔╗╔══╗   ╔╗╔╗
            ╚╗╔╝ ╚╝   ╚╝╚╝   ╚╝╚╗╔╝   ╚╝╚╝
             ║║    ╔╗ ╔╗ ╔╗   ╔╗ ║║     ╔╗
             ║║    ╚╝ ╚╝ ╚╝   ╚╝ ║║     ╚╝
             ╚╝         ╔╗    ╔╗  ║║      ╔╗
                          ╚╝    ╚╝  ╚╝      ╚╝
            """)

        print("✅ Bot is now running and waiting for updates via webhooks...")
        print("Press Ctrl+C to stop.\n")

    except Exception as e:
        logger.error("🔥 FATAL ERROR during startup:")
        logger.error(traceback.format_exc())
        raise

async def on_shutdown():
    global _shutting_down, _background_tasks
    if _shutting_down:
        logger.info("Shutdown already in progress, skipping")
        return
    _shutting_down = True

    logger.info("Shutting down...")

    # Отменяем фоновые задачи
    if _background_tasks:
        logger.info(f"Cancelling {len(_background_tasks)} background tasks...")
        for task in _background_tasks:
            if not task.done():
                task.cancel()
        try:
            await asyncio.wait_for(asyncio.gather(*_background_tasks, return_exceptions=True), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("Background tasks did not finish within timeout")
        _background_tasks.clear()

    # Удаляем вебхуки и закрываем сессии ботов
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

    if internal_runner:
        try:
            await internal_runner.cleanup()
            logger.info("Internal API cleaned up")
        except Exception as e:
            logger.error(f"Error cleaning internal API: {e}")

    if engine:
        try:
            await engine.dispose()
            logger.info("Database engine disposed")
        except Exception as e:
            logger.error(f"Error disposing engine: {e}")

    logger.info("Shutdown complete.")

async def shutdown_with_timeout():
    try:
        await asyncio.wait_for(on_shutdown(), timeout=10.0)
    except asyncio.TimeoutError:
        logger.error("Shutdown timed out after 10 seconds, forcing exit")
    except Exception as e:
        logger.exception(f"Unexpected error during shutdown: {e}")

async def main():
    try:
        await on_startup()
    except Exception:
        logger.error("Startup failed, exiting.")
        sys.exit(1)

    stop_event = asyncio.Event()

    def signal_handler():
        logger.info("Received stop signal, initiating graceful shutdown...")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    try:
        await stop_event.wait()
    except asyncio.CancelledError:
        logger.info("Main task cancelled")
    finally:
        await shutdown_with_timeout()
        await asyncio.sleep(0.5)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutdown by user (KeyboardInterrupt)")
    except Exception as e:
        logger.exception("Fatal error")
        sys.exit(1)