import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession
from web.services.auth import AuthService
from db.models import WebUser
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


@pytest.fixture
def mock_async_db():
    """Создаёт мок-асинхронную сессию БД."""
    db = MagicMock(spec=AsyncSession)
    db.execute = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_authenticate_user_correct_password(mock_async_db):
    hashed = pwd_context.hash("secret")
    expected_user = WebUser(email="test@example.com", hashed_password=hashed)
    
    # Мокаем выполнение запроса
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = expected_user
    mock_async_db.execute.return_value = mock_result

    user = await AuthService.authenticate_user(mock_async_db, "test@example.com", "secret")
    assert user == expected_user


@pytest.mark.asyncio
async def test_authenticate_user_wrong_password(mock_async_db):
    hashed = pwd_context.hash("secret")
    expected_user = WebUser(email="test@example.com", hashed_password=hashed)
    
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = expected_user
    mock_async_db.execute.return_value = mock_result

    user = await AuthService.authenticate_user(mock_async_db, "test@example.com", "wrong")
    assert user is None


@pytest.mark.asyncio
async def test_authenticate_user_nonexistent(mock_async_db):
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = None
    mock_async_db.execute.return_value = mock_result

    user = await AuthService.authenticate_user(mock_async_db, "nobody@example.com", "pass")
    assert user is None