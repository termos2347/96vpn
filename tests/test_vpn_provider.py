import pytest
from unittest.mock import AsyncMock, patch
from services.vpn_provider import XUIVPNProvider


@pytest.mark.asyncio
async def test_vpn_provider_create_client():
    provider = XUIVPNProvider()
    # Мокаем low‑level запрос, чтобы не обращаться к реальной панели
    async def mock_retry(*args, **kwargs):
        return {"success": True}
    provider._retry_request = mock_retry
    # login не нужен, если _is_authenticated = True
    provider._is_authenticated = True

    result = await provider.create_client("test@example.com")
    assert result is not None
    assert "uuid" in result
    assert "subId" in result


@pytest.mark.asyncio
async def test_vpn_provider_get_subscription_link():
    provider = XUIVPNProvider()
    provider._server_address = "185.5.75.235"
    provider.sub_port = 2096

    link = provider.get_subscription_link("abc123")
    assert link == "http://185.5.75.235:2096/sub/abc123"


@pytest.mark.asyncio
async def test_vpn_provider_revoke_client():
    provider = XUIVPNProvider()
    async def mock_retry(*args, **kwargs):
        return {"success": True}
    provider._retry_request = mock_retry
    provider._is_authenticated = True

    result = await provider.revoke_client("some-uuid")
    assert result is True