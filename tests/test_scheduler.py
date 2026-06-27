import pytest
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from services.scheduler import check_expired_subscriptions
from db.models import BotUser

@pytest.mark.asyncio
async def test_check_expired_subscriptions(test_session, mock_bot):
    user_id = 123
    async with test_session.begin():
        user = BotUser(
            telegram_id=user_id,
            vpn_subscription_end=datetime.now(timezone.utc) - timedelta(days=1),
            vpn_client_id="test-uuid"
        )
        test_session.add(user)

    with patch('services.scheduler.get_vpn_manager') as mock_get_manager:
        mock_manager = AsyncMock()
        mock_manager.revoke_key = AsyncMock(return_value=True)
        mock_get_manager.return_value = mock_manager

        # Запускаем задачу и отменяем через 0.2 сек (чтобы она успела выполнить одну итерацию)
        with patch('services.scheduler.asyncio.sleep', new=AsyncMock()) as mock_sleep:
            task = asyncio.create_task(check_expired_subscriptions(mock_bot))
            await asyncio.sleep(0.2)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        mock_manager.revoke_key.assert_called_once_with(user_id)
        mock_bot.send_message.assert_called_once()