from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from config import DATABASE_URL
from .models import Base

engine = create_async_engine(
    DATABASE_URL,
    echo=True,
    pool_pre_ping=True,   # Проверяет соединение перед отправкой запроса
    pool_recycle=300,      # Пересоздаёт соединение каждые 5 минут
    pool_size=5,
    max_overflow=10
)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)