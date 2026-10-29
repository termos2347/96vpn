import asyncio
import logging
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import TypeVar

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import DATABASE_URL

logger = logging.getLogger(__name__)

# ---------- Движок ----------
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=300,
    connect_args={
        "server_settings": {
            "statement_timeout": "30s",  # 30 секунд на выполнение запроса
            "lock_timeout": "15s",  # 15 секунд на ожидание блокировки
        }
    },
)

# async_sessionmaker — официальный способ для async (SQLAlchemy 2.0+).
# Pylance понимает тип корректно: AsyncSessionLocal() -> AsyncSession.
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# ---------- Декоратор повторных попыток ----------
T = TypeVar("T")


def retry_db_operation(max_retries=3, delay=1, backoff=2):
    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception: Exception | None = None
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    # Здесь мы намеренно перехватываем все исключения,
                    # чтобы повторить операцию – это стандартный паттерн.
                    last_exception = e
                    logger.warning(
                        f"DB operation {func.__name__} failed "
                        f"(attempt {attempt + 1}/{max_retries}): {e}"
                    )
                    if attempt < max_retries - 1:
                        await asyncio.sleep(delay * (backoff**attempt))
            logger.error(f"All {max_retries} retries failed for {func.__name__}")
            if last_exception is not None:
                raise last_exception
            raise RuntimeError(
                f"{func.__name__} failed with max_retries={max_retries} "
                "but no exception was captured"
            )

        return wrapper

    return decorator


async def close_db():
    await engine.dispose()
    logger.info("Database engine disposed")