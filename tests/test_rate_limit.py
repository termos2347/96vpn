import pytest
from unittest.mock import AsyncMock, MagicMock
from aiogram.types import Message
from utils.decorators import rate_limit, _user_actions


@pytest.fixture(autouse=True)
def clear_rate_limits():
    _user_actions.clear()


def make_message(user_id: int, username: str = "test"):
    """Создаёт мок-сообщение, которое пройдёт проверку isinstance."""
    msg = MagicMock()
    msg.__class__ = Message               # чтобы isinstance отработал
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    msg.from_user.username = username
    msg.answer = AsyncMock()              # чтобы декоратор не падал при вызове answer
    return msg


@pytest.mark.asyncio
async def test_rate_limit_allows_first_call():
    message = make_message(123)
    called = False

    @rate_limit(max_per_minute=3)
    async def handler(msg):
        nonlocal called
        called = True

    await handler(message)
    assert called is True


@pytest.mark.asyncio
async def test_rate_limit_blocks_excessive_calls():
    message = make_message(456, "spammer")

    @rate_limit(max_per_minute=2)
    async def handler(msg):
        return "ok"

    await handler(message)
    await handler(message)

    # Третий вызов должен быть заблокирован
    result = await handler(message)
    assert result is None


@pytest.mark.asyncio
async def test_rate_limit_resets_after_window():
    message = make_message(789, "resetter")

    @rate_limit(max_per_minute=1)
    async def handler(msg):
        return "ok"

    result = await handler(message)
    assert result == "ok"

    # Второй вызов блокируется
    result = await handler(message)
    assert result is None

    # Очищаем хранилище – имитируем истечение окна
    _user_actions.clear()

    # Теперь снова должно работать
    result = await handler(message)
    assert result == "ok"