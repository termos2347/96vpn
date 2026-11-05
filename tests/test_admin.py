# tests/test_admin.py
"""Тесты админ-бота: команды, регистрация декораторов, поведение."""

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from aiogram.types import Chat, Message, User

from admin import bot as admin_module
from admin.bot import cmd_grant, cmd_revoke, dp
from config import settings


# ============================================================
# Регистрация команд (бывший test_admin_handlers.py)
# ============================================================

EXPECTED_FUNCTIONS = {
    "cmd_start": "start",
    "cmd_menu": "menu",
    "cmd_health": "health",
    "cmd_errors": "errors",
    "cmd_grant": "grant",
    "cmd_revoke": "revoke",
    "cmd_stats": "stats",
    "cmd_broadcast": "broadcast",
    "cmd_broadcast_media": "broadcast_media",
    "cmd_userinfo": "userinfo",
    "cmd_show_yookassa_ips": "yookassa_ips",
    "cmd_set_yookassa_ips": "set_yookassa_ips",
}


def _registered_callback_names() -> set[str]:
    names: set[str] = set()
    for handler in dp.message.handlers:
        cb = getattr(handler, "callback", None)
        if cb is None:
            continue
        name = getattr(cb, "__name__", None)
        if name:
            names.add(name)
    return names


def test_dp_message_has_handlers():
    n = len(dp.message.handlers)
    names = sorted(_registered_callback_names())
    assert n > 0, (
        f"dp.message.handlers = {n} (пусто). "
        f"В admin/bot.py отсутствуют декораторы "
        f"@dp.message(Command(...)). Callbacks: {names}."
    )


def test_all_admin_command_handlers_registered():
    registered = _registered_callback_names()
    expected = set(EXPECTED_FUNCTIONS.keys())
    missing = expected - registered
    assert not missing, (
        f"Функции без @dp.message(Command(...)): {sorted(missing)}. "
        f"Зарегистрированы: {sorted(registered)}."
    )


@pytest.mark.parametrize(
    "func_name,command_name",
    sorted(EXPECTED_FUNCTIONS.items()),
    ids=[f"/{cmd}" for cmd in sorted(EXPECTED_FUNCTIONS.values())],
)
def test_individual_command_handler_registered(
    func_name: str, command_name: str
):
    registered = _registered_callback_names()
    assert func_name in registered, (
        f"Команда /{command_name} не зарегистрирована: {func_name} "
        f"отсутствует в dp.message.handlers."
    )


def test_broadcast_callback_registered():
    has_callbacks = any(
        handler.filters for handler in dp.callback_query.handlers
    )
    assert has_callbacks, "Нет callback-обработчиков в dp.callback_query"


def test_grant_revoke_callable_from_text():
    assert hasattr(admin_module, "cmd_grant")
    assert hasattr(admin_module, "cmd_revoke")
    assert hasattr(admin_module, "cmd_stats")
    assert hasattr(admin_module, "cmd_broadcast")


# ============================================================
# Поведение команд (бывший test_admin_commands.py)
# ============================================================


@pytest.fixture
def admin_message() -> Any:
    msg = AsyncMock(spec=Message)
    msg.from_user = User(
        id=int(settings.ADMIN_CHAT_ID), is_bot=False, first_name="Admin"
    )
    msg.chat = Chat(id=int(settings.ADMIN_CHAT_ID), type="private")
    msg.answer = AsyncMock()
    msg.bot = AsyncMock()
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