# tests/test_vpn_provider.py
from unittest.mock import AsyncMock, patch

import pytest

from services.vpn_provider import XUIVPNProvider


@pytest.fixture
def provider():
    return XUIVPNProvider(
        base_url="https://test.com:443/api",
        api_token="test-token-1234567890abcdef",
        inbound_id=1,
        sub_port=2096,
    )


@pytest.mark.asyncio
async def test_create_client(provider):
    with patch.object(
        provider,
        "_retry_request",
        new=AsyncMock(return_value={"success": True}),
    ):
        result = await provider.create_client("test@example.com", "sub12345678")
        assert result is not None
        assert "uuid" in result
        assert "subId" in result


@pytest.mark.asyncio
async def test_revoke_client_success(provider):
    with patch.object(
        provider,
        "_retry_request",
        new=AsyncMock(return_value={"success": True}),
    ) as mock_retry:
        result = await provider.revoke_client("sub123")
        assert result is True
        mock_retry.assert_called_once()


def test_get_subscription_link(provider):
    link = provider.get_subscription_link("sub123")
    assert link == "https://test.com:2096/sub/sub123"