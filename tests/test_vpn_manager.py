import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from services.vpn_manager import VPNManager


@pytest.fixture
def mock_server_pool():
    """Фикстура для мок-пула серверов."""
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
    from services.vpn_provider import XUIVPNProvider
    provider = XUIVPNProvider()
    assert provider.base_url is not None
    assert provider.username is not None
    assert provider.inbound_id > 0
    assert provider.sub_port > 0
    await provider.close()


def test_config_loading():
    from config import VPN_PRICES, BYPASS_PRICES, TOKEN, DATABASE_URL
    assert TOKEN
    assert DATABASE_URL
    assert 'rub' in VPN_PRICES
    assert 'stars' in VPN_PRICES
    assert 'usdt' in VPN_PRICES
    assert '1m' in VPN_PRICES['rub']


def test_vpn_prices_structure():
    from config import VPN_PRICES
    for currency, periods in VPN_PRICES.items():
        assert isinstance(periods, dict)
        assert '1m' in periods or '3m' in periods or '6m' in periods
        for period, price in periods.items():
            assert isinstance(price, (int, float))
            assert price > 0


@pytest.mark.asyncio
async def test_vpn_manager_create_key(mock_server_pool):
    manager = VPNManager(mock_server_pool)

    # Мокаем провайдера – get_subscription_link синхронный, поэтому MagicMock
    mock_provider = AsyncMock()
    mock_provider.create_client.return_value = {"uuid": "test-uuid", "subId": "test-subid"}
    mock_provider.get_subscription_link = MagicMock(return_value="http://test.link/sub/test-subid")
    mock_server_pool.get_provider.return_value = mock_provider

    with patch('services.vpn_manager.get_or_create_bot_user', new_callable=AsyncMock) as mock_get_user:
        mock_user = MagicMock()
        mock_user.telegram_id = 123
        mock_user.vpn_client_id = None
        mock_user.server_id = None
        mock_get_user.return_value = mock_user

        with patch('services.vpn_manager.set_vpn_client_id', new_callable=AsyncMock) as mock_set_client:
            with patch('services.vpn_manager.set_vpn_server_id', new_callable=AsyncMock) as mock_set_server:
                result = await manager.create_key(123, 30)

                assert result == "http://test.link/sub/test-subid"
                mock_server_pool.get_server.assert_called_once()
                mock_provider.create_client.assert_called_once()
                mock_set_client.assert_called_once_with(123, "test-uuid")
                mock_set_server.assert_called_once_with(123, 1)


@pytest.mark.asyncio
async def test_vpn_manager_revoke_key(mock_server_pool):
    manager = VPNManager(mock_server_pool)

    mock_provider = AsyncMock()
    mock_provider.revoke_client.return_value = True
    mock_server_pool.get_provider.return_value = mock_provider

    with patch('services.vpn_manager.get_or_create_bot_user', new_callable=AsyncMock) as mock_get_user:
        mock_user = MagicMock()
        mock_user.vpn_client_id = "test-uuid"
        mock_user.server_id = 1
        mock_get_user.return_value = mock_user

        with patch('services.vpn_manager.set_vpn_client_id', new_callable=AsyncMock) as mock_set_client:
            with patch('services.vpn_manager.set_vpn_server_id', new_callable=AsyncMock) as mock_set_server:
                result = await manager.revoke_key(123)

                assert result is True
                mock_server_pool.get_provider.assert_called_once_with(1)
                mock_provider.revoke_client.assert_called_once_with("test-uuid")
                mock_set_client.assert_called_once_with(123, None)
                mock_set_server.assert_called_once_with(123, None)


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


@pytest.mark.asyncio
async def test_vpn_provider_create_client():
    from services.vpn_provider import XUIVPNProvider
    provider = XUIVPNProvider()
    # Подменяем внутренний _retry_request, чтобы не ходить в сеть
    provider._retry_request = AsyncMock(return_value={"success": True})
    provider._is_authenticated = True

    result = await provider.create_client("test@example.com")
    assert result is not None
    assert "uuid" in result
    assert "subId" in result