import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from db.base import AsyncSessionLocal

@pytest.fixture(scope="session")
async def async_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session