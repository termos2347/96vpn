import asyncio
import logging
import os
from alembic.config import Config
from alembic import command
from sqlalchemy import text
from config import settings
from db.base import engine

logger = logging.getLogger(__name__)

async def run_migrations():
    """Автоматически применяет миграции Alembic с блокировкой PostgreSQL advisory lock."""
    if settings.DEBUG:
        logger.info("DEBUG mode: skipping automatic migrations")
        return

    if not engine:
        logger.warning("Database engine not initialized, skipping migrations")
        return

    alembic_ini_path = os.path.join(os.path.dirname(__file__), "..", "alembic.ini")
    alembic_cfg = Config(alembic_ini_path)

    logger.info("Running database migrations with advisory lock...")

    if 'postgresql' in settings.DATABASE_URL:
        async with engine.begin() as conn:
            lock_acquired = False
            try:
                for attempt in range(60):
                    lock_acquired = await conn.scalar(text("SELECT pg_try_advisory_lock(12345)"))
                    if lock_acquired:
                        break
                    if attempt == 0:
                        logger.warning("Another migration is running, waiting up to 60 seconds...")
                    await asyncio.sleep(1)

                if not lock_acquired:
                    logger.error("Could not acquire advisory lock after 60 seconds, aborting migrations")
                    return

                logger.info("Advisory lock acquired, running migrations...")
                command.upgrade(alembic_cfg, "head")
                logger.info("Migrations applied successfully")

            except Exception as e:
                logger.error(f"Migration failed: {e}")
                raise
            finally:
                if lock_acquired:
                    try:
                        await conn.execute(text("SELECT pg_advisory_unlock(12345)"))
                        logger.debug("Advisory lock released")
                    except Exception as unlock_err:
                        logger.error(f"Failed to release advisory lock: {unlock_err}")
    else:
        command.upgrade(alembic_cfg, "head")
        logger.info("Migrations applied (no advisory lock, non-PostgreSQL DB)")