import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from db.models import Base
from services.vpn_provider import XUIVPNProvider


@pytest.fixture(scope="session")
def event_loop():
    return asyncio.get_event_loop()


@pytest.fixture(scope="function")
async def test_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture(scope="function")
async def test_session(test_engine):
    async_session = sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session() as session:
        yield session


@pytest.fixture
def mock_yookassa_payment():
    with patch("services.payment_yookassa.Payment") as mock_payment_class:
        mock_create = MagicMock()
        mock_find = MagicMock()
        payment_mock = MagicMock()
        payment_mock.id = "test_payment_123"
        payment_mock.status = "pending"
        payment_mock.confirmation = MagicMock()
        payment_mock.confirmation.confirmation_url = "https://yookassa.ru/confirm"
        payment_mock.amount = MagicMock(value="100.00", currency="RUB")
        mock_create.return_value = payment_mock
        mock_find.return_value = payment_mock
        mock_payment_class.create = mock_create
        mock_payment_class.find_one = mock_find
        yield mock_payment_class


@pytest.fixture
def mock_bot():
    bot = AsyncMock(spec=Bot)
    bot.send_message = AsyncMock()
    bot.send_photo = AsyncMock()
    bot.send_document = AsyncMock()
    bot.send_video = AsyncMock()
    bot.send_animation = AsyncMock()
    return bot


@pytest.fixture
def mock_vpn_provider():
    provider = AsyncMock(spec=XUIVPNProvider)
    provider.login = AsyncMock(return_value=True)
    provider.create_client = AsyncMock(
        return_value={"uuid": "test-uuid", "subId": "test-sub"}
    )
    provider.revoke_client = AsyncMock(return_value=True)
    provider.get_client_by_uuid = AsyncMock(
        return_value={
            "uuid": "test-uuid",
            "subId": "test-sub",
            "email": "test@example.com",
        }
    )
    provider.get_subscription_link = MagicMock(
        return_value="https://test.com/sub/test-sub"
    )
    provider._is_authenticated = True
    return provider
