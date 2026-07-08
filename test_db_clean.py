#!/usr/bin/env python3
"""
Диагностический скрипт для проверки подключения к БД и выполнения тестовых запросов.
Убирает проблемный параметр channel_binding и логирует всё в консоль.
"""

import asyncio
import logging
import time
from urllib.parse import urlparse, parse_qs, urlunparse, urlencode
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

# ======== Настройка логирования ========
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ======== Очистка URL от channel_binding ========
def clean_db_url(url: str) -> str:
    """Удаляет параметр channel_binding из URL и нормализует схему."""
    parsed = urlparse(url)
    # Убираем channel_binding
    query_params = parse_qs(parsed.query)
    query_params.pop('channel_binding', None)
    new_query = urlencode(query_params, doseq=True)
    # Меняем схему на postgresql:// для совместимости (если нужно)
    # Оставляем как есть, но для прямого asyncpg будем менять отдельно
    cleaned = urlunparse(parsed._replace(query=new_query))
    return cleaned

# Используем переменную окружения
from config import DATABASE_URL
CLEAN_URL = clean_db_url(DATABASE_URL)
logger.info(f"Original DATABASE_URL: {DATABASE_URL}")
logger.info(f"Cleaned DATABASE_URL: {CLEAN_URL}")

# ======== Основная тестовая функция ========
async def test_db():
    logger.info("=== Starting DB diagnostic test ===")

    # 1. Создаём движок с очищенным URL (без connect_args)
    engine = create_async_engine(
        CLEAN_URL,
        echo=False,
        pool_size=1,
        max_overflow=0,
        pool_pre_ping=True,
        pool_recycle=60,
    )
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        # 2. Проверка подключения (простой SELECT)
        logger.info("Testing simple SELECT 1...")
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            val = result.scalar()
            logger.info(f"✅ SELECT 1 result: {val}")

        # 3. Проверка таблицы bot_users
        logger.info("Checking bot_users table...")
        async with AsyncSessionLocal() as session:
            count_result = await session.execute(text("SELECT COUNT(*) FROM bot_users"))
            count = count_result.scalar()
            logger.info(f"📊 Total rows in bot_users: {count}")

            if count > 0:
                # 4. Получить одного пользователя для теста
                row = await session.execute(
                    text("SELECT id, telegram_id, vpn_client_id, vpn_subscription_end FROM bot_users LIMIT 1")
                )
                user = row.first()
                logger.info(f"📌 Sample user: id={user.id}, tg_id={user.telegram_id}, client_id={user.vpn_client_id}, end={user.vpn_subscription_end}")

                # 5. Тестовый UPDATE (замер времени)
                test_id = user.id
                logger.info(f"⏳ Performing test UPDATE on user id={test_id}...")
                start_time = time.time()
                try:
                    await session.execute(
                        text("UPDATE bot_users SET updated_at = :now WHERE id = :id"),
                        {"now": datetime.now(timezone.utc), "id": test_id}
                    )
                    await session.commit()
                    elapsed = time.time() - start_time
                    logger.info(f"✅ UPDATE executed successfully in {elapsed:.2f} seconds")
                except Exception as e:
                    logger.error(f"❌ UPDATE failed: {e}")

        # 6. (Опционально) Проверка индексов
        logger.info("📋 Checking indexes on bot_users...")
        async with AsyncSessionLocal() as session:
            idx_result = await session.execute(
                text("""
                    SELECT indexname, indexdef 
                    FROM pg_indexes 
                    WHERE tablename = 'bot_users'
                """)
            )
            indexes = idx_result.fetchall()
            for idx in indexes:
                logger.info(f"   Index: {idx.indexname} -> {idx.indexdef}")

        # 7. (Опционально) Проверка через прямой asyncpg, если установлен
        try:
            import asyncpg
            logger.info("Testing direct asyncpg connection...")
            # Для прямого asyncpg нужно убрать +asyncpg из схемы
            dsn = CLEAN_URL.replace('postgresql+asyncpg://', 'postgresql://')
            # Убираем параметры запроса, т.к. они могут не поддерживаться
            # Можно просто передать без query
            dsn_no_query = dsn.split('?')[0]
            conn = await asyncpg.connect(dsn_no_query)
            val = await conn.fetchval("SELECT 1")
            logger.info(f"✅ asyncpg SELECT 1 result: {val}")
            await conn.close()
        except ImportError:
            logger.warning("⚠️ asyncpg not installed, skipping direct test")
        except Exception as e:
            logger.error(f"❌ asyncpg direct test failed: {e}")

        logger.info("=== DB diagnostic test completed successfully ===")

    except Exception as e:
        logger.error(f"❌ Test failed: {e}", exc_info=True)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(test_db())