import os
import asyncio
import logging
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
    
    # Путь к alembic.ini относительно корня проекта
    alembic_ini_path = os.path.join(os.path.dirname(__file__), "..", "alembic.ini")
    alembic_cfg = Config(alembic_ini_path)

    logger.info("Running database migrations with advisory lock...")
    alembic_cfg = Config("alembic.ini")

    # Используем блокировку PostgreSQL (только для PostgreSQL, для SQLite пропускаем)
    if 'postgresql' in settings.DATABASE_URL:
        async with engine.begin() as conn:
            try:
                # Захватываем advisory lock (идентификатор 12345 – произвольный)
                await conn.execute(text("SELECT pg_advisory_lock(12345)"))
                logger.info("Advisory lock acquired")
                
                # Выполняем миграции
                command.upgrade(alembic_cfg, "head")
                
                # Освобождаем блокировку
                await conn.execute(text("SELECT pg_advisory_unlock(12345)"))
                logger.info("Advisory lock released, migrations applied")
            except Exception as e:
                logger.error(f"Migration failed: {e}")
                # Пытаемся освободить блокировку в случае ошибки
                try:
                    await conn.execute(text("SELECT pg_advisory_unlock(12345)"))
                except Exception:
                    pass
                raise
    else:
        # Для SQLite или других БД – просто выполняем миграции без блокировки
        command.upgrade(alembic_cfg, "head")
        logger.info("Migrations applied (no advisory lock, non-PostgreSQL DB)")