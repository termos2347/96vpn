import asyncio
import logging
import signal
import sys
import traceback
from aiohttp import web
from aiogram import Bot, Dispatcher
from sqlalchemy import text

from config import TOKEN, settings
from handlers import router as main_router, init_vpn_components, set_vpn_manager, get_vpn_manager
from handlers.common import setup_bot_commands
from services.scheduler import start_scheduler
from services.vpn_manager import VPNManager
from services.vpn_provider import XUIVPNProvider
from db.base import engine
from internal_api import create_internal_app
import admin.bot
from utils.logger import setup_logger

# Проверка миграций
from alembic.config import Config
from alembic.script import ScriptDirectory

try:
    from pyfiglet import Figlet
    HAS_PYFIGLET = True
except ImportError:
    HAS_PYFIGLET = False

def handle_asyncio_exception(loop, context):
    logger = logging.getLogger(__name__)
    logger.error(f"Asyncio exception: {context.get('message')}")
    exception = context.get('exception')
    if exception:
        logger.exception("Exception details", exc_info=exception)
        error_text = f"Asyncio exception: {exception}"
    else:
        error_text = f"Asyncio exception: {context.get('message')}"
    from admin.bot import log_error
    log_error(error_text, notify_admin=True)

setup_logger()
logger = logging.getLogger(__name__)

main_bot = None
main_dp = None
internal_runner = None
_shutting_down = False
_background_tasks = []


async def check_db_with_retry(max_retries: int = 5, delay: float = 2.0) -> bool:
    for attempt in range(1, max_retries + 1):
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            logger.info("✅ Database connection successful")
            return True
        except Exception as e:
            logger.warning(f"DB connection attempt {attempt}/{max_retries} failed: {e}")
            if attempt == max_retries:
                raise
            await asyncio.sleep(delay)
    return False


async def check_migrations() -> None:
    if getattr(settings, "SKIP_MIGRATION_CHECK", False):
        logger.warning("⚠️ Skipping migration check (SKIP_MIGRATION_CHECK=true)")
        return
    alembic_cfg = Config("alembic.ini")
    script = ScriptDirectory.from_config(alembic_cfg)
    head_rev = script.get_current_head()
    if head_rev is None:
        logger.error("❌ No migration revisions found. Please run 'alembic upgrade head'.")
        raise RuntimeError("No Alembic revisions")
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT to_regclass('alembic_version')"))
        if result.scalar() is None:
            logger.error("❌ Table 'alembic_version' does not exist. Database not initialized with migrations.")
            raise RuntimeError("Database not migrated. Run 'alembic upgrade head'.")
        result = await conn.execute(text("SELECT version_num FROM alembic_version"))
        row = result.fetchone()
        if row is None:
            logger.error("❌ alembic_version table is empty.")
            raise RuntimeError("Alembic version missing")
        current_rev = row[0]
    if current_rev != head_rev:
        logger.error(f"❌ Database revision mismatch! Current: {current_rev}, Expected (head): {head_rev}.")
        raise RuntimeError("Migration mismatch")
    else:
        logger.info(f"✅ Database is up-to-date (revision {head_rev})")


async def set_webhook_with_retry(bot: Bot, url: str, secret_token: str,
                                 max_retries: int = 5, base_delay: float = 1.0) -> bool:
    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"Setting webhook to {url} (attempt {attempt}/{max_retries})...")
            await bot.set_webhook(url=url, secret_token=secret_token)
            info = await bot.get_webhook_info()
            if info.url == url:
                logger.info(f"✅ Webhook successfully set to {url}")
                return True
            else:
                logger.warning(f"Webhook URL mismatch: expected {url}, got {info.url}")
        except Exception as e:
            logger.error(f"Attempt {attempt} failed: {e}")
        if attempt < max_retries:
            delay = base_delay * (2 ** (attempt - 1))
            logger.info(f"Retrying in {delay} seconds...")
            await asyncio.sleep(delay)
    logger.error(f"❌ Failed to set webhook after {max_retries} attempts")
    return False


async def on_startup():
    global main_bot, main_dp, internal_runner, _background_tasks
    logger.info("=" * 50)
    logger.info("Starting VPN bot with webhooks...")
    logger.info("=" * 50)

    try:
        logger.info("Step 1/7: Checking database connection...")
        await check_db_with_retry()
        logger.info("✅ Database connection successful")

        await check_migrations()

        logger.info("Step 2/7: Initializing VPN components (single Master 3x-UI panel)...")
        provider = XUIVPNProvider(
            base_url=settings.XUI_MASTER_URL,
            username=settings.XUI_LOGIN,
            password=settings.XUI_PASSWORD,
            inbound_id=settings.XUI_INBOUND_ID,
            sub_port=settings.XUI_SUB_PORT
        )
        vpn_manager = VPNManager(provider)
        set_vpn_manager(vpn_manager)
        init_vpn_components()
        logger.info("✅ VPN components initialized")

        logger.info("Step 3/7: Starting admin bot...")
        await admin.bot.startup()
        logger.info("✅ Admin bot started")

        logger.info("Step 4/7: Initializing main bot...")
        main_bot = Bot(token=TOKEN)
        main_dp = Dispatcher()
        main_dp.include_router(main_router)
        await setup_bot_commands(main_bot)
        logger.info("✅ Main bot initialized")

        admin.bot.main_bot = main_bot

        logger.info("Step 5/7: Starting internal API server...")
        internal_app = create_internal_app(
            main_bot=main_bot,
            main_dp=main_dp,
            admin_bot=admin.bot.admin_bot,
            admin_dp=admin.bot.dp
        )
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

        logger.info("Step 6/7: Setting up webhooks with retry...")
        if not settings.WEBHOOK_URL or not settings.ADMIN_WEBHOOK_URL:
            raise ValueError("WEBHOOK_URL and ADMIN_WEBHOOK_URL are required")

        await main_bot.delete_webhook()
        await admin.bot.admin_bot.delete_webhook()

        if not await set_webhook_with_retry(main_bot, settings.WEBHOOK_URL, settings.WEBHOOK_SECRET):
            raise RuntimeError("Failed to set main bot webhook after retries")
        if not await set_webhook_with_retry(admin.bot.admin_bot, settings.ADMIN_WEBHOOK_URL, settings.ADMIN_WEBHOOK_SECRET):
            raise RuntimeError("Failed to set admin bot webhook after retries")

        logger.info("✅ Webhooks configured")

        logger.info("Step 7/7: Starting background tasks...")
        _background_tasks = await start_scheduler(main_bot)
        logger.info("✅ Background tasks started")

        print("\n" + "=" * 50)
        print("🎉 ALL SERVICES STARTED SUCCESSFULLY! 🎉")
        print("=" * 50)

        if HAS_PYFIGLET:
            try:
                f = Figlet(font='slant')
                ascii_art = f.renderText('96VPN BOT')
                print("\n" + ascii_art)
            except Exception:
                pass
        else:
            print("""
             ╔═══╗ ╔╗   ╔╗╔══╗   ╔╗╔══╗
            ╚╗╔╗║ ║║   ║║╚╣╠╝   ║║╚╣╠╝
             ║║║║ ║║ ╔╗║║ ║║    ║║ ║║
             ║║║║ ║╚═╝║║ ║║    ║║ ║║
             ╚╝╚╝ ╚═══╝╚╝ ╚╝    ╚╝ ╚╝
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
        return
    _shutting_down = True
    logger.info("Shutting down...")

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

    # --- Закрываем VPN-провайдер (освобождаем HTTP-сессии) ---
    vpn_manager = get_vpn_manager()
    if vpn_manager and hasattr(vpn_manager, 'provider'):
        try:
            await vpn_manager.provider.close()
            logger.info("VPN provider closed")
        except Exception as e:
            logger.warning(f"Error closing VPN provider: {e}")

    if main_bot:
        try:
            await main_bot.delete_webhook()
        except Exception:
            pass
        try:
            await main_bot.session.close()
        except Exception:
            pass

    if admin.bot.admin_bot:
        try:
            await admin.bot.admin_bot.delete_webhook()
        except Exception:
            pass
        try:
            await admin.bot.admin_bot.session.close()
        except Exception:
            pass

    await admin.bot.shutdown()

    if internal_runner:
        try:
            await internal_runner.cleanup()
        except Exception:
            pass

    if engine:
        try:
            await engine.dispose()
        except Exception:
            pass

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
    loop.set_exception_handler(handle_asyncio_exception)

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