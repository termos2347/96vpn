import asyncio
import logging
from alembic.config import Config
from alembic import command
from config import settings

logger = logging.getLogger(__name__)

async def run_migrations():
    """Автоматически применяет миграции Alembic при старте (только не в DEBUG)"""
    if settings.DEBUG:
        logger.info("DEBUG mode: skipping automatic migrations")
        return
    
    logger.info("Running database migrations...")
    try:
        alembic_cfg = Config("alembic.ini")
        command.upgrade(alembic_cfg, "head")
        logger.info("Migrations applied successfully")
    except Exception as e:
        logger.error(f"Failed to run migrations: {e}")
        raise