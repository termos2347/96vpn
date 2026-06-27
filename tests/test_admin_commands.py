import pytest
from unittest.mock import AsyncMock, patch
from aiogram.types import Message, Chat, User
from admin.bot import cmd_grant, cmd_revoke
from db.models import BotUser
from config import settings

@pytest.fixture
def admin_message():
    msg = AsyncMock(spec=Message)
    msg.from_user = User(id=int(settings.ADMIN_CHAT_ID), is_bot=False, first_name="Admin")
    msg.chat = Chat(id=int(settings.ADMIN_CHAT_ID), type="private")
    msg.answer = AsyncMock()
    return msg

@pytest.mark.asyncio
async def test_grant_command(admin_message, test_session):
    with patch('admin.bot.get_vpn_manager') as mock_get_manager:
        mock_manager = AsyncMock()
        mock_manager.create_key = AsyncMock(return_value="https://test.com/sub/xyz")
        mock_get_manager.return_value = mock_manager

        async with test_session.begin():
            user = BotUser(telegram_id=123)
            test_session.add(user)

        admin_message.text = "/grant 123 30"
        with patch('admin.bot.AsyncSessionLocal', return_value=test_session):
            await cmd_grant(admin_message)

        mock_manager.create_key.assert_called_once_with(123, 30)
        admin_message.answer.assert_called_once()

@pytest.mark.asyncio
async def test_revoke_command(admin_message, test_session):
    with patch('admin.bot.get_vpn_manager') as mock_get_manager:
        mock_manager = AsyncMock()
        mock_manager.revoke_key = AsyncMock(return_value=True)
        mock_get_manager.return_value = mock_manager

        admin_message.text = "/revoke 123"
        with patch('admin.bot.AsyncSessionLocal', return_value=test_session):
            await cmd_revoke(admin_message)

        mock_manager.revoke_key.assert_called_once_with(123)
        admin_message.answer.assert_called_once()