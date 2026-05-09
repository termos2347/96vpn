import os
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from config import DATABASE_URL
from .models import Base, WebUser, BotUser, BotPayment, Category, Prompt

is_sqlite = 'sqlite' in DATABASE_URL

def _split_db_url(url: str):
    parsed = urlparse(url)
    return parsed, dict(parse_qs(parsed.query))

# --- Асинхронный движок (бот) ---
if DATABASE_URL:
    if is_sqlite:
        async_db_url = DATABASE_URL.replace('sqlite:///', 'sqlite+aiosqlite:///')
        engine = create_async_engine(
            async_db_url,
            echo=False,
            pool_pre_ping=True,
            pool_recycle=600,
            pool_size=5,
            max_overflow=10
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
        parsed, qs = _split_db_url(DATABASE_URL)
        if 'ssl' in qs:
            ssl_value = qs['ssl'][0] if qs['ssl'] else 'require'
            qs.pop('ssl', None)
            qs['sslmode'] = [ssl_value]
        qs.pop('channel_binding', None)
        new_query = urlencode(qs, doseq=True)
        sync_url = urlunparse(parsed._replace(query=new_query))
        sync_engine = create_engine(
            sync_url,
            echo=False,
            pool_pre_ping=True,
            pool_recycle=600,
            connect_args={
                "keepalives": 1,
                "keepalives_idle": 30,
                "keepalives_interval": 10,
                "keepalives_count": 5,
            }
        )
else:
    sync_engine = None

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=sync_engine) if sync_engine else None

def get_db():
    if SessionLocal is None:
        raise RuntimeError("Database not configured")
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

async def init_db():
    if not engine:
        return
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

def init_sync_db():
    if sync_engine is None:
        raise RuntimeError("Database not configured")
    Base.metadata.create_all(bind=sync_engine)
    
async def get_async_db():
    async with AsyncSessionLocal() as session:
        yield session