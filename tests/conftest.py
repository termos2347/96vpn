import pytest
from unittest.mock import AsyncMock
from aiogram import Bot

@pytest.fixture
def bot():
    bot = AsyncMock(spec=Bot)
    bot.send_message = AsyncMock()
    return bot