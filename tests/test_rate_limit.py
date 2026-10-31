# tests/test_rate_limit.py
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.types import CallbackQuery, Message, User

from utils.decorators import rate_limit


def make_message(user_id: int, username: str = "test") -> Any:
    """
    Возвращает MagicMock со spec=Message.
    isinstance(msg, Message) → True (spec подменяет __class__),
    поэтому декоратор rate_limit работает с ним как с настоящим Message.
    """
    msg = MagicMock(spec=Message)
    msg.from_user = MagicMock(spec=User)
    msg.from_user.id = user_id
    msg.from_user.username = username
    msg.answer = AsyncMock()
    return msg


@pytest.mark.asyncio
async def test_rate_limit_allows_first_call():
    message = make_message(123)
    called = False

    @rate_limit(max_per_minute=3)
    async def handler(msg):
        nonlocal called
        called = True

    with patch("utils.decorators.redis_service") as mock_redis:
        mock_redis.rate_limit_check = AsyncMock(return_value=(True, 1))
        await handler(message)

    assert called is True


@pytest.mark.asyncio
async def test_rate_limit_blocks_excessive_calls():
    message = make_message(456, "spammer")

    @rate_limit(max_per_minute=2)
    async def handler(msg):
        return "ok"

    with patch("utils.decorators.redis_service") as mock_redis:
        mock_redis.rate_limit_check = AsyncMock(
            side_effect=[(True, 1), (True, 2), (False, 3)]
        )
        assert await handler(message) == "ok"
        assert await handler(message) == "ok"
        assert await handler(message) is None

    message.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_rate_limit_fail_open_on_redis_error():
    """При недоступности Redis декоратор пропускает запрос."""
    message = make_message(789, "resetter")

    @rate_limit(max_per_minute=1)
    async def handler(msg):
        return "ok"

    with patch("utils.decorators.redis_service") as mock_redis:
        mock_redis.rate_limit_check = AsyncMock(
            side_effect=RuntimeError("Redis not connected")
        )
        result = await handler(message)

    assert result == "ok"


@pytest.mark.asyncio
async def test_rate_limit_skips_anonymous():
    """Анонимные админы каналов (from_user=None) не лимитируются."""
    message = make_message(0)
    message.from_user = None

    @rate_limit(max_per_minute=1)
    async def handler(msg):
        return "ok"

    with patch("utils.decorators.redis_service") as mock_redis:
        mock_redis.rate_limit_check = AsyncMock(return_value=(True, 1))
        result = await handler(message)

    assert result == "ok"
    mock_redis.rate_limit_check.assert_not_awaited()


@pytest.mark.asyncio
async def test_rate_limit_callback_query():
    """Для CallbackQuery показывается alert-предупреждение."""
    cb = MagicMock(spec=CallbackQuery)
    cb.from_user = MagicMock(spec=User)
    cb.from_user.id = 999
    cb.answer = AsyncMock()

    @rate_limit(max_per_minute=1)
    async def handler(c):
        return "ok"

    with patch("utils.decorators.redis_service") as mock_redis:
        mock_redis.rate_limit_check = AsyncMock(return_value=(False, 2))
        result = await handler(cb)

    assert result is None
    cb.answer.assert_awaited_once_with(
        "⏱️ Слишком много запросов. Подождите немного...", show_alert=False
    )