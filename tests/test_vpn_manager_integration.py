import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from sqlalchemy import select

from services.vpn_manager import VPNManager
from db.models import BotUser

@pytest.mark.asyncio
async def test_create_key_new_user(test_session, mock_server_pool):
    manager = VPNManager(mock_server_pool)
    user_id = 999

    with patch('services.vpn_manager.get_or_create_bot_user', new_callable=AsyncMock) as mock_get:
        user = BotUser(telegram_id=user_id)
        mock_get.return_value = user

        link = await manager.create_key(user_id, 30)
        assert link == "https://test.com/sub/test-sub"

        mock_server_pool.get_server.assert_called_once()
        mock_server_pool.get_provider.assert_called_once()
        provider = await mock_server_pool.get_provider()
        provider.create_client.assert_called_once_with(f"user_{user_id}@96vpn.bot")

@pytest.mark.asyncio
async def test_revoke_key_unsafe(test_session, mock_server_pool):
    manager = VPNManager(mock_server_pool)
    user_id = 777
    async with test_session.begin():
        user = BotUser(
            telegram_id=user_id,
            vpn_client_id="test-uuid",
            server_id=1,
            vpn_subscription_end=datetime.now(timezone.utc) + timedelta(days=10)
        )
        test_session.add(user)

    provider = await mock_server_pool.get_provider()
    provider.revoke_client.return_value = True

    result = await manager._revoke_key_unsafe(user_id, test_session)
    assert result is True

    stmt = select(BotUser).where(BotUser.telegram_id == user_id)
    updated_user = (await test_session.execute(stmt)).scalar_one()
    assert updated_user.vpn_client_id is None
    assert updated_user.server_id is None
    assert updated_user.vpn_subscription_end < datetime.now(timezone.utc)