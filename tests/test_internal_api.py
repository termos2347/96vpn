# tests/test_internal_api.py
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy.ext.asyncio import async_sessionmaker

from config import INTERNAL_API_SECRET
from internal_api import create_internal_app


@pytest.fixture
def internal_app(mock_bot):
    return create_internal_app(
        main_bot=mock_bot, main_dp=None, admin_bot=None, admin_dp=None
    )


@pytest.fixture
async def client(internal_app):
    """TestServer оборачивает Application — так требует новый aiohttp."""
    async with TestClient(TestServer(internal_app)) as c:
        yield c


@pytest.fixture
def patched_session_local(test_engine):
    """Подменяет internal_api.AsyncSessionLocal на in-memory SQLite."""
    session_maker = async_sessionmaker(test_engine, expire_on_commit=False)
    with patch("internal_api.AsyncSessionLocal", session_maker):
        yield session_maker


@pytest.mark.asyncio
async def test_activate_success(client, mock_bot, patched_session_local):
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
        mock_manager.create_vpn_key = AsyncMock(
            return_value="https://test.com/sub/xyz"
        )
        mock_get_manager.return_value = mock_manager

        resp = await client.post("/activate", json=payload, headers=headers)
        assert resp.status == 200
        data = await resp.json()
        assert data == {"status": "ok"}

        mock_activate.assert_called_once()
        mock_manager.create_vpn_key.assert_called_once_with(123)
        mock_bot.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_activate_missing_fields(client):
    payload = {"telegram_id": 123}
    headers = {"Authorization": f"Bearer {INTERNAL_API_SECRET}"}
    resp = await client.post("/activate", json=payload, headers=headers)
    assert resp.status == 400
    data = await resp.json()
    assert "error" in data


@pytest.mark.asyncio
async def test_activate_unauthorized(client):
    payload = {"telegram_id": 123, "product_type": "vpn", "period": "1m"}
    resp = await client.post("/activate", json=payload)
    assert resp.status == 401