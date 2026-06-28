import asyncio
import logging
from functools import wraps
from typing import Type, Tuple, Callable, Any
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.exc import OperationalError, DBAPIError
from asyncpg.exceptions import ConnectionDoesNotExistError

from config import DATABASE_URL
from .models import Base

logger = logging.getLogger(__name__)

# --- Асинхронный движок для PostgreSQL ---
if DATABASE_URL:
    parsed = urlparse(DATABASE_URL)
    query_params = parse_qs(parsed.query)

    # Удаляем несовместимые с asyncpg параметры (если они есть)
    query_params.pop('channel_binding', None)
    # Если параметр sslmode указан, asyncpg его поддерживает, оставляем.

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

# ---------- ДЕКОРАТОР ДЛЯ ПОВТОРНЫХ ПОПЫТОК ПРИ ОШИБКАХ СОЕДИНЕНИЯ ----------
# Кортеж исключений, которые считаем временными (сетевыми)
RETRYABLE_EXCEPTIONS = (
    OperationalError,
    DBAPIError,
    ConnectionDoesNotExistError,
    # можно добавить TimeoutError, asyncio.TimeoutError при необходимости
)

def retry_db_operation(
    max_retries: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 5.0,
    exceptions: Tuple[Type[Exception], ...] = RETRYABLE_EXCEPTIONS,
) -> Callable:
    """
    Декоратор для асинхронных функций, выполняющих операции с БД.
    При возникновении одного из указанных исключений функция повторяется
    с экспоненциальной задержкой.
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(1, max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    logger.warning(
                        f"DB operation {func.__name__} failed (attempt {attempt}/{max_retries}): {e}"
                    )
                    if attempt == max_retries:
                        break
                    delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                    await asyncio.sleep(delay)
                except Exception as e:
                    # Неожиданная ошибка – пробрасываем сразу
                    logger.error(f"Unexpected error in {func.__name__}: {e}", exc_info=True)
                    raise
            # Все попытки исчерпаны
            logger.error(f"All {max_retries} retries failed for {func.__name__}")
            raise last_exception
        return wrapper
    return decorator

# ---------- Вспомогательные функции (уже были) ----------
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