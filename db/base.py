import os
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from config import DATABASE_URL
from .models import Base

is_sqlite = 'sqlite' in DATABASE_URL

def _split_db_url(url: str):
    """Разбирает URL и возвращает (базовый URL, параметры query)."""
    parsed = urlparse(url)
    return parsed, dict(parse_qs(parsed.query))

# --- Асинхронный движок (бот) ---
if DATABASE_URL:
    if is_sqlite:
        async_db_url = DATABASE_URL.replace('sqlite:///', 'sqlite+aiosqlite:///')
    else:
        parsed, qs = _split_db_url(DATABASE_URL)
        # Удаляем параметры, которые мешают asyncpg
        qs.pop('channel_binding', None)
        # Оставляем только sslmode (он поддерживается asyncpg)
        # Пересобираем URL с драйвером asyncpg
        new_query = urlencode(qs, doseq=True)
        async_db_url = urlunparse(parsed._replace(
            scheme='postgresql+asyncpg',
            query=new_query
        ))

    engine = create_async_engine(
        async_db_url,
        echo=False,
        pool_pre_ping=True,
        pool_recycle=600,
        pool_size=5,
        max_overflow=10
    )
else:
    engine = None

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession) if engine else None

# --- Синхронный движок (веб) ---
if DATABASE_URL:
    if is_sqlite:
        sync_engine = create_engine(
            DATABASE_URL,
            connect_args={"check_same_thread": False},
            echo=False
        )
    else:
        # Для psycopg2 оставляем URL как есть (postgresql://...?sslmode=require)
        sync_engine = create_engine(DATABASE_URL, echo=False)
else:
    sync_engine = None

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=sync_engine) if sync_engine else None

# Dependency для FastAPI
def get_db():
    """Зависимость для получения сессии БД в FastAPI"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

async def init_db():
    """Инициализация БД (для асинхронного engine)"""
    if not engine:
        return
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)