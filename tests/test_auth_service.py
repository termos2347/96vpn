import pytest
from unittest.mock import MagicMock, patch
from sqlalchemy.orm import Session
from web.services.auth import AuthService
from db.models import User
from passlib.context import CryptContext

# Используем тот же контекст, что и в AuthService
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


@pytest.fixture
def mock_db():
    """Создаёт мок-сессию БД."""
    db = MagicMock(spec=Session)
    return db


@pytest.mark.asyncio
async def test_authenticate_user_correct_password(mock_db):
    hashed = pwd_context.hash("secret")
    expected_user = User(email="test@example.com", hashed_password=hashed)
    mock_db.execute.return_value.scalars().first.return_value = expected_user

    user = await AuthService.authenticate_user(mock_db, "test@example.com", "secret")
    assert user == expected_user


@pytest.mark.asyncio
async def test_authenticate_user_wrong_password(mock_db):
    hashed = pwd_context.hash("secret")
    expected_user = User(email="test@example.com", hashed_password=hashed)
    mock_db.execute.return_value.scalars().first.return_value = expected_user

    user = await AuthService.authenticate_user(mock_db, "test@example.com", "wrong")
    assert user is None


@pytest.mark.asyncio
async def test_authenticate_user_nonexistent(mock_db):
    mock_db.execute.return_value.scalars().first.return_value = None

    user = await AuthService.authenticate_user(mock_db, "nobody@example.com", "pass")
    assert user is None