# tests/test_admin_commands.py
from unittest.mock import AsyncMock, patch

import pytest
from aiogram.types import Chat, Message, User

from admin.bot import cmd_grant, cmd_revoke
from config import settings


@pytest.fixture
def admin_message():
    msg = AsyncMock(spec=Message)
    msg.from_user = User(
        id=int(settings.ADMIN_CHAT_ID), is_bot=False, first_name="Admin"
    )
    msg.chat = Chat(id=int(settings.ADMIN_CHAT_ID), type="private")
    msg.answer = AsyncMock()
    msg.bot = AsyncMock()  # нужен для message.bot.send_message в cmd_grant/revoke
    return msg


@pytest.mark.asyncio
async def test_grant_command(admin_message):
    with patch("admin.bot.get_vpn_manager") as mock_get_manager:
        mock_manager = AsyncMock()
        mock_manager.grant_subscription = AsyncMock(
            return_value="https://test.com/sub/xyz"
        )
        mock_get_manager.return_value = mock_manager

        admin_message.text = "/grant 123 30"
        await cmd_grant(admin_message)

        mock_manager.grant_subscription.assert_called_once_with(123, 30)
        admin_message.answer.assert_called_once()


@pytest.mark.asyncio
async def test_revoke_command(admin_message):
    with patch("admin.bot.get_vpn_manager") as mock_get_manager:
        mock_manager = AsyncMock()
        mock_manager.revoke_key = AsyncMock(return_value=True)
        mock_get_manager.return_value = mock_manager

        admin_message.text = "/revoke 123"
        await cmd_revoke(admin_message)

        mock_manager.revoke_key.assert_called_once_with(123)
        admin_message.answer.assert_called_once()