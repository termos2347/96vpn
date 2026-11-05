import asyncio
import logging
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import TypeVar

from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import DATABASE_URL, get_asyncpg_ssl, settings

logger = logging.getLogger(__name__)

_ssl_config = get_asyncpg_ssl(settings.DATABASE_URL)

_connect_args: dict = {
    "server_settings": {
        "statement_timeout": "30s",
        "lock_timeout": "15s",
    }
}
if _ssl_config is not None:
    _connect_args["ssl"] = _ssl_config

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=300,
    connect_args=_connect_args,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

T = TypeVar("T")

# BUGFIX: добавляем asyncpg-исключения к retryable.
# SQLAlchemy OperationalError/InterfaceError не всегда оборачивают
# connection-level сбои asyncpg (ConnectionDoesNotExistError,
# TooManyConnectionsError) — часть транзиентных сбоев не ретраилась.
try:
    from asyncpg.exceptions import (
        PostgresConnectionError,
        TooManyConnectionsError,
    )

    _ASYNC_PG_RETRYABLE: tuple[type[BaseException], ...] = (
        PostgresConnectionError,
        TooManyConnectionsError,
    )
except ImportError:  # asyncpg не установлен (напр. при сборке docs)
    _ASYNC_PG_RETRYABLE = ()

_RETRYABLE_DB_ERRORS = (OperationalError, InterfaceError, *_ASYNC_PG_RETRYABLE)


def retry_db_operation(max_retries=3, delay=1, backoff=2):
    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception: Exception | None = None
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except _RETRYABLE_DB_ERRORS as e:
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
                f"{func.__name__} failed with max_retries={max_retries}"
            )

        return wrapper

    return decorator


async def close_db():
    await engine.dispose()
    logger.info("Database engine disposed")
