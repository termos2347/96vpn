import os
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from config import DATABASE_URL
from .models import Base

is_sqlite = 'sqlite' in DATABASE_URL

def _split_db_url(url: str):
    parsed = urlparse(url)
    return parsed, dict(parse_qs(parsed.query))

# --- Асинхронный движок (бот и веб) ---
if DATABASE_URL:
    if is_sqlite:
        # для SQLite настройки проще
        async_db_url = DATABASE_URL.replace('sqlite:///', 'sqlite+aiosqlite:///')
        engine = create_async_engine(
            async_db_url,
            echo=False,
            pool_pre_ping=True,
            pool_recycle=600,
            pool_size=10,
            max_overflow=20,
        )
    else:
        parsed, qs = _split_db_url(DATABASE_URL)
        qs.pop('channel_binding', None)
        new_query = urlencode(qs, doseq=True)
        async_db_url = urlunparse(parsed._replace(
            scheme='postgresql+asyncpg',
            query=new_query
        ))
        engine = create_async_engine(
            async_db_url,
            echo=False,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
            pool_timeout=30,
            pool_recycle=300,
            pool_use_lifo=True,
            connect_args={
                "timeout": 10,
                "command_timeout": 60,
                "server_settings": {"application_name": "96vpn_bot"}
            }
        )
else:
    engine = None

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession) if engine else None

async def init_db():
    if not engine:
        return
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def get_async_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()