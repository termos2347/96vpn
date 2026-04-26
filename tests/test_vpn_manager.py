import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from services.vpn_manager import VPNManager

@pytest.mark.asyncio
async def test_vpn_manager_create_key():
    """Test VPNManager.create_key with mocked provider."""
    manager = VPNManager()

    # Mock the provider methods
    with patch.object(manager.provider, 'create_client', new_callable=AsyncMock) as mock_create:
        mock_create.return_value = {"uuid": "test-uuid", "subId": "test-subid"}

        with patch('services.vpn_manager.get_or_create_user') as mock_get_user:
            mock_user = MagicMock()
            mock_user.user_id = 123
            mock_get_user.return_value = mock_user

            with patch('services.vpn_manager.set_vpn_client_id', new_callable=AsyncMock) as mock_set_id:
                mock_set_id.return_value = True

                result = await manager.create_key(123, 30)

                assert result is not None
                assert "test-subid" in result
                mock_create.assert_called_once()
                mock_set_id.assert_called_once_with(123, "test-uuid")

@pytest.mark.asyncio
async def test_vpn_manager_revoke_key():
    """Test VPNManager.revoke_key with mocked provider."""
    manager = VPNManager()

    with patch('services.vpn_manager.get_or_create_user') as mock_get_user:
        mock_user = MagicMock()
        mock_user.vpn_client_id = "test-uuid"
        mock_get_user.return_value = mock_user

        with patch.object(manager.provider, 'revoke_client', new_callable=AsyncMock) as mock_revoke:
            mock_revoke.return_value = True

            with patch('services.vpn_manager.set_vpn_client_id', new_callable=AsyncMock) as mock_set_id:
                mock_set_id.return_value = True

                result = await manager.revoke_key(123)

                assert result is True
                mock_revoke.assert_called_once_with("test-uuid")
                mock_set_id.assert_called_once_with(123, None)

@pytest.mark.asyncio
async def test_vpn_manager_revoke_key_no_client():
    """Test VPNManager.revoke_key when user has no client."""
    manager = VPNManager()

    with patch('services.vpn_manager.get_or_create_user') as mock_get_user:
        mock_user = MagicMock()
        mock_user.vpn_client_id = None
        mock_get_user.return_value = mock_user

        result = await manager.revoke_key(123)

        assert result is True  # Should return True for no-op