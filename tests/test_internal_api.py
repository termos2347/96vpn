from unittest.mock import AsyncMock, patch

import pytest
from aiohttp.test_utils import TestClient

from config import INTERNAL_API_SECRET
from internal_api import create_internal_app


@pytest.fixture
def internal_app(mock_bot):
    app = create_internal_app(
        main_bot=mock_bot, main_dp=None, admin_bot=None, admin_dp=None
    )
    return app


@pytest.mark.asyncio
async def test_activate_success(internal_app, mock_bot):
    client = await TestClient(internal_app).__aenter__()
    payload = {
        "telegram_id": 123,
        "product_type": "vpn",
        "period": "1m",
        "payment_id": "test_pay",
    }
    headers = {"Authorization": f"Bearer {INTERNAL_API_SECRET}"}

    with patch(
        "internal_api.activate_subscription", new=AsyncMock(return_value=True)
    ) as mock_activate, patch("internal_api.get_vpn_manager") as mock_get_manager:
        mock_manager = AsyncMock()
        mock_manager.create_key = AsyncMock(return_value="https://test.com/sub/xyz")
        mock_get_manager.return_value = mock_manager

        resp = await client.post("/activate", json=payload, headers=headers)
        assert resp.status == 200
        data = await resp.json()
        assert data == {"status": "ok"}

        mock_activate.assert_called_once()
        mock_manager.create_key.assert_called_once_with(123, 30)
        mock_bot.send_message.assert_called_once()

    await client.close()


@pytest.mark.asyncio
async def test_activate_missing_fields(internal_app):
    client = await TestClient(internal_app).__aenter__()
    payload = {"telegram_id": 123}
    headers = {"Authorization": f"Bearer {INTERNAL_API_SECRET}"}
    resp = await client.post("/activate", json=payload, headers=headers)
    assert resp.status == 400
    data = await resp.json()
    assert "error" in data
    await client.close()


@pytest.mark.asyncio
async def test_activate_unauthorized(internal_app):
    client = await TestClient(internal_app).__aenter__()
    payload = {"telegram_id": 123, "product_type": "vpn", "period": "1m"}
    resp = await client.post("/activate", json=payload)
    assert resp.status == 401
    await client.close()
