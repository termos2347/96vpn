import pytest
from unittest.mock import AsyncMock, MagicMock
from web.services.auth import AuthService, hash_password
from db.models import WebUser


def test_hash_and_verify():
    from web.services.auth import verify_password
    password = "secret"
    hashed = hash_password(password)
    assert verify_password(password, hashed)
    assert not verify_password("wrong", hashed)


@pytest.mark.asyncio
async def test_authenticate_user_correct_password():
    db_mock = AsyncMock()
    hashed = hash_password("secret")
    fake_user = WebUser(email="test@example.com", hashed_password=hashed)

    # Мокаем цепочку: db.execute -> result.scalars().first()
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = fake_user
    db_mock.execute.return_value = mock_result

    user = await AuthService.authenticate_user(db_mock, "test@example.com", "secret")
    assert user == fake_user


@pytest.mark.asyncio
async def test_authenticate_user_wrong_password():
    db_mock = AsyncMock()
    hashed = hash_password("secret")
    fake_user = WebUser(email="test@example.com", hashed_password=hashed)
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = fake_user
    db_mock.execute.return_value = mock_result

    user = await AuthService.authenticate_user(db_mock, "test@example.com", "wrong")
    assert user is None


@pytest.mark.asyncio
async def test_authenticate_user_nonexistent():
    db_mock = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = None
    db_mock.execute.return_value = mock_result

    user = await AuthService.authenticate_user(db_mock, "nobody@example.com", "pass")
    assert user is None


@pytest.mark.asyncio
async def test_create_user_duplicate():
    db_mock = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = WebUser()
    db_mock.execute.return_value = mock_result

    user = await AuthService.create_user(db_mock, "test@example.com", "pass")
    assert user is None