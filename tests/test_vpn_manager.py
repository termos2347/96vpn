import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from services.vpn_manager import VPNManager


@pytest.mark.asyncio
async def test_vpn_manager_initialization():
    manager = VPNManager()
    assert manager is not None
    assert manager.provider is not None


@pytest.mark.asyncio
async def test_vpn_provider_initialization():
    from services.vpn_provider import XUIVPNProvider
    provider = XUIVPNProvider()
    assert provider is not None
    assert provider.base_url
    assert provider.username
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
    from config import VPN_PRICES, BYPASS_PRICES
    for currency, periods in VPN_PRICES.items():
        assert isinstance(periods, dict)
        assert '1m' in periods or '3m' in periods or '6m' in periods
        for period, price in periods.items():
            assert isinstance(price, (int, float))
            assert price > 0


@pytest.mark.asyncio
async def test_vpn_manager_create_key():
    manager = VPNManager()

    # Патчим функции, импортированные в vpn_manager
    with patch('services.vpn_manager.get_or_create_bot_user', new_callable=AsyncMock) as mock_get_user:
        with patch('services.vpn_manager.set_vpn_client_id', new_callable=AsyncMock) as mock_set_id:
            with patch.object(manager.provider, 'create_client', new_callable=AsyncMock) as mock_create:

                mock_user = MagicMock()
                mock_user.telegram_id = 123
                mock_user.vpn_client_id = None  # у пользователя нет активного ключа
                mock_get_user.return_value = mock_user

                mock_create.return_value = {"uuid": "test-uuid", "subId": "test-subid"}

                result = await manager.create_key(123, 30)

                assert result is not None
                assert "test-subid" in result
                mock_create.assert_called_once()
                mock_set_id.assert_called_once_with(123, "test-uuid")


@pytest.mark.asyncio
async def test_vpn_manager_revoke_key():
    manager = VPNManager()

    with patch('services.vpn_manager.get_or_create_bot_user', new_callable=AsyncMock) as mock_get_user:
        with patch('services.vpn_manager.set_vpn_client_id', new_callable=AsyncMock) as mock_set_id:
            with patch.object(manager.provider, 'revoke_client', new_callable=AsyncMock) as mock_revoke:

                mock_user = MagicMock()
                mock_user.vpn_client_id = "test-uuid"
                mock_get_user.return_value = mock_user

                mock_revoke.return_value = True

                result = await manager.revoke_key(123)

                assert result is True
                mock_revoke.assert_called_once_with("test-uuid")
                mock_set_id.assert_called_once_with(123, None)


@pytest.mark.asyncio
async def test_vpn_manager_revoke_key_no_client():
    manager = VPNManager()

    with patch('services.vpn_manager.get_or_create_bot_user', new_callable=AsyncMock) as mock_get_user:
        mock_user = MagicMock()
        mock_user.vpn_client_id = None
        mock_get_user.return_value = mock_user

        with patch.object(manager.provider, 'revoke_client', new_callable=AsyncMock) as mock_revoke:
            result = await manager.revoke_key(123)
            assert result is True
            mock_revoke.assert_not_called()
            # set_vpn_client_id не должна вызываться, поэтому не мокаем её


@pytest.mark.asyncio
async def test_vpn_provider_create_client():
    from services.vpn_provider import XUIVPNProvider
    provider = XUIVPNProvider()

    async def mock_retry(*args, **kwargs):
        return {"success": True}
    provider._retry_request = mock_retry
    provider._is_authenticated = True

    result = await provider.create_client("test@example.com")
    assert result is not None
    assert "uuid" in result
    assert "subId" in result