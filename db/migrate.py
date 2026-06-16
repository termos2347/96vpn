import asyncio
import logging
import os
import subprocess
import sys
from sqlalchemy import text
from config import settings
from db.base import engine

logger = logging.getLogger(__name__)

async def run_migrations():
    """Применяет миграции Alembic, используя advisory lock и отдельный процесс."""
    if settings.DEBUG:
        logger.info("DEBUG mode: skipping automatic migrations")
        return

    if not engine:
        logger.warning("Database engine not initialized, skipping migrations")
        return

    alembic_ini_path = os.path.join(os.path.dirname(__file__), "..", "alembic.ini")
    if not os.path.exists(alembic_ini_path):
        logger.error("alembic.ini not found")
        return

    logger.info("Running database migrations with advisory lock...")

    # Получаем блокировку через отдельное подключение, в режиме AUTOCOMMIT
    if 'postgresql' in settings.DATABASE_URL:
        lock_acquired = False
        async with engine.connect() as conn:
            await conn.execution_options(isolation_level="AUTOCOMMIT")
            try:
                for attempt in range(60):
                    result = await conn.execute(text("SELECT pg_try_advisory_lock(12345)"))
                    lock_acquired = result.scalar()
                    if lock_acquired:
                        break
                    if attempt == 0:
                        logger.warning("Another migration is running, waiting up to 60 seconds...")
                    await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"Error acquiring advisory lock: {e}")
                return

        if not lock_acquired:
            logger.error("Could not acquire advisory lock after 60 seconds, aborting migrations")
            return

        try:
            logger.info("Advisory lock acquired, running migrations via subprocess...")
            env = os.environ.copy()
            env["PYTHONPATH"] = os.path.dirname(os.path.dirname(__file__))
            cmd = [sys.executable, "-m", "alembic", "-c", alembic_ini_path, "upgrade", "head"]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30.0)

            if process.returncode != 0:
                logger.error(f"Migration subprocess failed with code {process.returncode}")
                if stderr:
                    logger.error(f"stderr: {stderr.decode()}")
                if stdout:
                    logger.info(f"stdout: {stdout.decode()}")
            else:
                logger.info("Migrations applied successfully")
                if stdout:
                    logger.info(stdout.decode())
        except asyncio.TimeoutError:
            logger.error("Migration subprocess timed out after 30 seconds")
            try:
                process.kill()
            except:
                pass
        except Exception as e:
            logger.error(f"Migration error: {e}")
        finally:
            # Освобождаем блокировку
            async with engine.connect() as conn:
                await conn.execution_options(isolation_level="AUTOCOMMIT")
                try:
                    await conn.execute(text("SELECT pg_advisory_unlock(12345)"))
                    logger.debug("Advisory lock released")
                except Exception as unlock_err:
                    logger.error(f"Failed to release advisory lock: {unlock_err}")
    else:
        # Для SQLite или других БД – просто выполняем через subprocess без блокировки
        logger.warning("Non-PostgreSQL DB, running migrations without advisory lock")
        cmd = [sys.executable, "-m", "alembic", "-c", alembic_ini_path, "upgrade", "head"]
        process = await asyncio.create_subprocess_exec(*cmd)
        await process.wait()
        if process.returncode == 0:
            logger.info("Migrations applied")
        else:
            logger.error("Migrations failed")