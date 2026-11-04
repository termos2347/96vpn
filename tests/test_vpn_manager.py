# tests/test_vpn_manager.py
"""Тесты VPNManager без roundtrip через БД.

SQLite не хранит timezone — колонка DateTime(timezone=True) возвращает
naive datetime при чтении (PostgreSQL возвращает aware). Прод на PG
работает, но тесты на SQLite ловят TypeError при сравнении naive/aware.

Поэтому здесь объекты БД не читаются из SQLite. Вместо этого:
- мокаем AsyncSessionLocal на пустой context manager;
- мокаем get_or_create_bot_user — возвращает ORM-объект, созданный
  в тесте, с datetime, заданным напрямую (aware UTC);
- мокаем _save_client_id и update_vpn_subscription.

Тестируется логика VPNManager (idempotency, guard-ветки, взаимодействие
с provider'ом), а не SQLAlchemy.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from db.models import BotUser
from services.vpn_manager import VPNManager


@pytest.fixture
def mock_provider():
    provider = AsyncMock()
    provider.create_client = AsyncMock(
        return_value={"uuid": "uuid-1", "subId": "sub-1"}
    )
    provider.get_subscription_link = MagicMock(
        return_value="https://test.com/sub/sub-1"
    )
    provider.get_client_by_email = AsyncMock(return_value=None)
    provider.get_client_by_sub_id = AsyncMock(return_value=None)
    provider.revoke_client = AsyncMock(return_value=True)
    return provider


@pytest.fixture
def manager(mock_provider):
    return VPNManager(mock_provider)


def _fake_user(
    telegram_id: int = 123,
    vpn_end: datetime | None = None,
    client_id: str | None = None,
) -> BotUser:
    """ORM-объект без привязки к сессии — подставляется через мок.

    vpn_end задаётся напрямую (aware UTC), поэтому get_or_create_link
    не падает на сравнении с datetime.now(timezone.utc).
    """
    user = BotUser(telegram_id=telegram_id)
    user.vpn_subscription_end = vpn_end
    user.vpn_client_id = client_id
    return user


def _mock_session_ctx():
    """Заменяет `async with AsyncSessionLocal() as session:`.

    Внутри `async with session.begin():` — тоже context manager (no-op).
    Реального обращения к БД нет.
    """
    session = AsyncMock()
    begin_ctx = AsyncMock()
    begin_ctx.__aenter__ = AsyncMock(return_value=None)
    begin_ctx.__aexit__ = AsyncMock(return_value=None)
    session.begin = MagicMock(return_value=begin_ctx)

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=None)
    return ctx, session


# ---------- create_vpn_key ----------


@pytest.mark.asyncio
async def test_create_vpn_key_idempotent(manager, mock_provider):
    """Повторный вызов не создаёт второго клиента на панели."""
    user = _fake_user(telegram_id=123)
    ctx, _ = _mock_session_ctx()

    with patch("services.vpn_manager.AsyncSessionLocal", return_value=ctx), \
         patch(
             "services.vpn_manager.get_or_create_bot_user",
             new=AsyncMock(return_value=user),
         ), \
         patch.object(manager, "_save_client_id", new=AsyncMock()):
        # Первый вызов — клиент создаётся
        link1 = await manager.create_vpn_key(123)
        assert link1 == "https://test.com/sub/sub-1"
        assert mock_provider.create_client.call_count == 1

        # Провайдер теперь "видит" клиента на панели
        mock_provider.get_client_by_email = AsyncMock(
            return_value={"subId": "sub-1"}
        )
        user.vpn_client_id = "uuid-1"

        # Второй вызов — переиспользует, create_client НЕ вызывается
        link2 = await manager.create_vpn_key(123)
        assert link2 == "https://test.com/sub/sub-1"
        assert mock_provider.create_client.call_count == 1


@pytest.mark.asyncio
async def test_create_vpn_key_does_not_touch_subscription(manager, mock_provider):
    """create_vpn_key не должен менять vpn_subscription_end."""
    original_end = datetime.now(timezone.utc) + timedelta(days=10)
    user = _fake_user(telegram_id=42, vpn_end=original_end)
    ctx, _ = _mock_session_ctx()

    with patch("services.vpn_manager.AsyncSessionLocal", return_value=ctx), \
         patch(
             "services.vpn_manager.get_or_create_bot_user",
             new=AsyncMock(return_value=user),
         ), \
         patch.object(manager, "_save_client_id", new=AsyncMock()):
        await manager.create_vpn_key(42)

    assert user.vpn_subscription_end == original_end


# ---------- grant_subscription ----------


@pytest.mark.asyncio
async def test_grant_subscription(manager, mock_provider):
    """grant_subscription продлевает и возвращает ссылку."""
    user = _fake_user(
        telegram_id=456,
        vpn_end=datetime.now(timezone.utc) + timedelta(days=30),
    )
    ctx, _ = _mock_session_ctx()

    with patch("services.vpn_manager.AsyncSessionLocal", return_value=ctx), \
         patch(
             "services.vpn_manager.get_or_create_bot_user",
             new=AsyncMock(return_value=user),
         ), \
         patch(
             "services.vpn_manager.update_vpn_subscription",
             new=AsyncMock(return_value=True),
         ), \
         patch.object(
             manager,
             "_find_existing_client",
             new=AsyncMock(return_value={"subId": "sub-1"}),
         ):
        link = await manager.grant_subscription(456, 30)
        assert link == "https://test.com/sub/sub-1"


@pytest.mark.asyncio
async def test_grant_subscription_update_failed(manager, mock_provider):
    """Если update_vpn_subscription вернул False — ссылка не возвращается."""
    user = _fake_user(telegram_id=457)
    ctx, _ = _mock_session_ctx()

    with patch("services.vpn_manager.AsyncSessionLocal", return_value=ctx), \
         patch(
             "services.vpn_manager.get_or_create_bot_user",
             new=AsyncMock(return_value=user),
         ), \
         patch(
             "services.vpn_manager.update_vpn_subscription",
             new=AsyncMock(return_value=False),
         ):
        link = await manager.grant_subscription(457, 30)
        assert link is None
        mock_provider.create_client.assert_not_called()


# ---------- revoke_key ----------


@pytest.mark.asyncio
async def test_revoke_key_no_client(manager, mock_provider):
    """Клиента нет — возвращаем True, revoke_client не вызывается."""
    user = _fake_user(telegram_id=789, client_id=None)
    ctx, _ = _mock_session_ctx()

    with patch("services.vpn_manager.AsyncSessionLocal", return_value=ctx), \
         patch(
             "services.vpn_manager.get_or_create_bot_user",
             new=AsyncMock(return_value=user),
         ):
        result = await manager.revoke_key(789)
        assert result is True
        mock_provider.revoke_client.assert_not_called()


@pytest.mark.asyncio
async def test_revoke_key_with_client(manager, mock_provider):
    """С клиентом — revoke_client вызывается с его id."""
    user = _fake_user(telegram_id=777, client_id="uuid-1")
    ctx, _ = _mock_session_ctx()

    with patch("services.vpn_manager.AsyncSessionLocal", return_value=ctx), \
         patch(
             "services.vpn_manager.get_or_create_bot_user",
             new=AsyncMock(return_value=user),
         ):
        result = await manager.revoke_key(777)
        assert result is True
        mock_provider.revoke_client.assert_called_once_with("uuid-1")


# ---------- get_or_create_link ----------


@pytest.mark.asyncio
async def test_get_or_create_link_expired(manager, mock_provider):
    """Истёкшая подписка — ссылка не создаётся."""
    user = _fake_user(
        telegram_id=999,
        vpn_end=datetime.now(timezone.utc) - timedelta(days=1),
    )
    ctx, _ = _mock_session_ctx()

    with patch("services.vpn_manager.AsyncSessionLocal", return_value=ctx), \
         patch(
             "services.vpn_manager.get_or_create_bot_user",
             new=AsyncMock(return_value=user),
         ):
        link = await manager.get_or_create_link(999)
        assert link is None
        mock_provider.create_client.assert_not_called()


@pytest.mark.asyncio
async def test_get_or_create_link_no_subscription(manager, mock_provider):
    """vpn_subscription_end = None — ссылка не создаётся."""
    user = _fake_user(telegram_id=998, vpn_end=None)
    ctx, _ = _mock_session_ctx()

    with patch("services.vpn_manager.AsyncSessionLocal", return_value=ctx), \
         patch(
             "services.vpn_manager.get_or_create_bot_user",
             new=AsyncMock(return_value=user),
         ):
        link = await manager.get_or_create_link(998)
        assert link is None
        mock_provider.create_client.assert_not_called()


@pytest.mark.asyncio
async def test_get_or_create_link_active(manager, mock_provider):
    """Активная подписка — создаётся ключ и возвращается ссылка."""
    user = _fake_user(
        telegram_id=555,
        vpn_end=datetime.now(timezone.utc) + timedelta(days=30),
    )
    ctx, _ = _mock_session_ctx()

    with patch("services.vpn_manager.AsyncSessionLocal", return_value=ctx), \
         patch(
             "services.vpn_manager.get_or_create_bot_user",
             new=AsyncMock(return_value=user),
         ), \
         patch.object(manager, "_save_client_id", new=AsyncMock()):
        link = await manager.get_or_create_link(555)
        assert link == "https://test.com/sub/sub-1"
        assert mock_provider.create_client.call_count == 1