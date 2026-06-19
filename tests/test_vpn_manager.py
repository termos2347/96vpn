import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from services.vpn_manager import VPNManager
from services.vpn_provider import XUIVPNProvider

@pytest.fixture
def mock_server_pool():
    pool = AsyncMock()
    pool.get_server = AsyncMock(return_value=MagicMock(id=1))
    pool.get_provider = AsyncMock()
    return pool

@pytest.mark.asyncio
async def test_vpn_manager_initialization(mock_server_pool):
    manager = VPNManager(mock_server_pool)
    assert manager is not None

@pytest.mark.asyncio
async def test_vpn_provider_initialization():
    provider = XUIVPNProvider(
        base_url="https://test.com",
        username="admin",
        password="pass",
        inbound_id=1,
        sub_port=2096
    )
    assert provider.base_url == "https://test.com"
    await provider.close()

@pytest.mark.asyncio
async def test_vpn_manager_revoke_key_no_client(mock_server_pool):
    manager = VPNManager(mock_server_pool)

    with patch('services.vpn_manager.get_or_create_bot_user', new_callable=AsyncMock) as mock_get_user:
        mock_user = MagicMock()
        mock_user.vpn_client_id = None
        mock_get_user.return_value = mock_user

        result = await manager.revoke_key(123)
        assert result is True
        mock_server_pool.get_provider.assert_not_called()