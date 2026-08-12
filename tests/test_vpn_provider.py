from unittest.mock import AsyncMock, patch

import pytest

from services.vpn_provider import XUIVPNProvider


@pytest.fixture
def provider():
    return XUIVPNProvider(
        base_url="https://test.com:443/api",
        username="admin",
        password="pass",
        inbound_id=1,
        sub_port=2096,
    )


@pytest.mark.asyncio
async def test_login_fail(provider):
    # Создаём мок для response
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={"success": False})

    # Создаём мок для контекстного менеджера
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
    mock_cm.__aexit__ = AsyncMock(return_value=None)

    # Мокаем session.post так, чтобы он возвращал контекстный менеджер
    with patch("aiohttp.ClientSession.post", return_value=mock_cm) as mock_post:
        result = await provider.login()
        assert result is False
        mock_post.assert_called_once()


@pytest.mark.asyncio
async def test_create_client(provider):
    provider._is_authenticated = True
    with patch(
        "services.vpn_provider.XUIVPNProvider._retry_request",
        new=AsyncMock(return_value={"success": True}),
    ):
        result = await provider.create_client("test@example.com")
        assert result is not None
        assert "uuid" in result
        assert "subId" in result


@pytest.mark.asyncio
async def test_get_subscription_link(provider):
    provider._server_address = "test.com"
    link = provider.get_subscription_link("sub123")
    assert link == "https://test.com:2096/sub/sub123"
