import os
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from config import DATABASE_URL
from .models import Base

# --- Асинхронный движок для PostgreSQL ---
if DATABASE_URL:
    parsed = urlparse(DATABASE_URL)
    query_params = parse_qs(parsed.query)

    # Удаляем несовместимые с asyncpg параметры (если они есть)
    query_params.pop('channel_binding', None)
    # Если параметр sslmode указан, asyncpg его поддерживает, оставляем.
    # Но для чистоты можно оставить как есть.

    new_query = urlencode(query_params, doseq=True)
    async_db_url = urlunparse(parsed._replace(
        scheme='postgresql+asyncpg',
        query=new_query
    ))

    engine = create_async_engine(
        async_db_url,
        echo=False,                     # В продакшне отключаем логи SQL
        pool_pre_ping=True,             # Проверка соединения перед использованием
        pool_size=5,                    # Размер пула соединений
        max_overflow=10,                # Дополнительные соединения при пиковой нагрузке
        pool_timeout=30,                # Таймаут ожидания соединения из пула
        pool_recycle=300,               # Пересоздавать соединения через 5 минут
        pool_use_lifo=True,             # Использовать LIFO для лучшей производительности
        connect_args={
            "timeout": 10,              # Таймаут подключения
            "command_timeout": 60,      # Таймаут выполнения запроса
            "server_settings": {"application_name": "96vpn_bot"}
        }
    )
else:
    engine = None
    raise RuntimeError("DATABASE_URL must be set in environment")

# Фабрика сессий
AsyncSessionLocal = async_sessionmaker(
    engine,
    expire_on_commit=False,
    class_=AsyncSession
)

async def init_db():
    """Создаёт таблицы (если их нет) – используется только при разработке."""
    if engine is None:
        return
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def get_async_db():
    """Генератор сессии для внедрения зависимостей (если нужно)."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()