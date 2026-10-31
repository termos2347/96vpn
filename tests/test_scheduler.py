# tests/test_scheduler.py
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from db.models import BotUser
from services.scheduler import check_expired_subscriptions


@pytest.mark.asyncio
async def test_check_expired_subscriptions(test_engine, mock_bot):
    user_id = 123
    session_maker = async_sessionmaker(test_engine, expire_on_commit=False)

    # Готовим данные в тестовой БД
    async with session_maker() as s:
        async with s.begin():
            s.add(
                BotUser(
                    telegram_id=user_id,
                    vpn_subscription_end=datetime.now(timezone.utc)
                    - timedelta(days=1),
                    vpn_client_id="test-uuid",
                )
            )

    # Патчим AsyncSessionLocal в scheduler'е на тестовый sessionmaker
    with patch("services.scheduler.AsyncSessionLocal", session_maker), patch(
        "services.scheduler.get_vpn_manager"
    ) as mock_get_manager:
        mock_manager = AsyncMock()
        mock_manager.revoke_key = AsyncMock(return_value=True)
        mock_get_manager.return_value = mock_manager

        # check_expired_subscriptions — не бесконечный цикл, а одна итерация;
        # await напрямую вместо create_task+cancel
        await check_expired_subscriptions(mock_bot)

        mock_manager.revoke_key.assert_called_once_with(user_id)
        mock_bot.send_message.assert_called_once()