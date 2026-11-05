# tests/test_regressions.py
"""Регрессионные тесты на конкретные баги. Если что-то сломается — упадёт здесь."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy.ext.asyncio import async_sessionmaker

from config import INTERNAL_API_SECRET
from db.models import BotUser
from internal_api import create_internal_app
from services.payment_yookassa import YookassaService, YookassaTransientError
from services.vpn_manager import VPNManager

# ============================================================
# Регрессия 1: /activate без payment_id НЕ активирует подписку
# ============================================================


@pytest.fixture
def internal_app(mock_bot):
    return create_internal_app(
        main_bot=mock_bot, main_dp=None, admin_bot=None, admin_dp=None
    )


@pytest.fixture
async def client(internal_app):
    async with TestClient(TestServer(internal_app)) as c:
        yield c


@pytest.mark.asyncio
async def test_activate_without_payment_id_rejected(client):
    payload = {"telegram_id": 123, "product_type": "vpn", "period": "1m"}
    headers = {"Authorization": f"Bearer {INTERNAL_API_SECRET}"}
    with patch(
        "internal_api.activate_subscription", new=AsyncMock()
    ) as mock_act:
        resp = await client.post("/activate", json=payload, headers=headers)
        assert resp.status == 400
        mock_act.assert_not_called()


# ============================================================
# Регрессия 2: вебхук без записи в БД → YookassaTransientError (500)
# ============================================================


@pytest.mark.asyncio
async def test_webhook_missing_db_payment_raises_transient(
    test_session, mock_bot
):
    webhook_data = {
        "event": "payment.succeeded",
        "object": {"id": "nonexistent_payment_xyz"},
    }
    service = YookassaService()
    with pytest.raises(YookassaTransientError):
        await service.process_webhook(webhook_data, test_session, mock_bot)


# ============================================================
# Регрессия 3: revoke_key без client_id сбрасывает подписку
# ============================================================


@pytest.mark.asyncio
async def test_revoke_key_without_client_resets_subscription(test_engine):
    session_maker = async_sessionmaker(test_engine, expire_on_commit=False)
    future_end = datetime.now(timezone.utc) + timedelta(days=30)
    async with session_maker() as s, s.begin():
        s.add(BotUser(telegram_id=777, vpn_subscription_end=future_end))

    provider = AsyncMock()
    manager = VPNManager(provider)

    with patch(
        "services.vpn_manager.AsyncSessionLocal", session_maker
    ), patch.object(
        manager, "_invalidate_cache", new=AsyncMock()
    ):
        result = await manager.revoke_key(777, require_expired=False)
        assert result is True

    async with session_maker() as s:
        user = await s.get(BotUser, 1)
        assert user is not None
        vpn_end = user.vpn_subscription_end
        assert vpn_end is not None
        # SQLite возвращает naive datetime для DateTime(timezone=True)
        if vpn_end.tzinfo is None:
            vpn_end = vpn_end.replace(tzinfo=timezone.utc)
        assert vpn_end < datetime.now(timezone.utc)


# ============================================================
# Регрессия 4: /set_yookassa_ips с мусором не перезаписывает файл
# ============================================================


@pytest.mark.asyncio
async def test_set_yookassa_ips_invalid_cidr_rejected():
    from aiogram.types import Chat, Message, User

    from admin.bot import cmd_set_yookassa_ips
    from config import settings

    msg = AsyncMock(spec=Message)
    msg.from_user = User(
        id=int(settings.ADMIN_CHAT_ID), is_bot=False, first_name="Admin"
    )
    msg.chat = Chat(id=int(settings.ADMIN_CHAT_ID), type="private")
    msg.answer = AsyncMock()
    msg.text = '/set_yookassa_ips ["garbage", "not-a-cidr"]'

    original = list(settings.YOOKASSA_TRUSTED_IPS)
    with patch("admin.bot.save_trusted_ips") as mock_save:
        await cmd_set_yookassa_ips(msg)
        mock_save.assert_not_called()
        assert settings.YOOKASSA_TRUSTED_IPS == original
        msg.answer.assert_called()


# ============================================================
# Регрессия 5: _find_existing_client находит по email-префиксу без client_id
# ============================================================


@pytest.mark.asyncio
async def test_find_existing_client_by_email_prefix_without_client_id():
    provider = AsyncMock()
    provider.get_all_clients = AsyncMock(
        return_value=[
            {"email": "tg_123_abcdef12", "subId": "sub-abc", "id": "uuid-x"},
            {"email": "tg_456_other1", "subId": "sub-def", "id": "uuid-y"},
        ]
    )
    manager = VPNManager(provider)

    result = await manager._find_existing_client(user_id=123, vpn_client_id=None)
    assert result is not None
    assert result["subId"] == "sub-abc"
