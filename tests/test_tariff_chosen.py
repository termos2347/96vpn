# tests/test_tariff_chosen.py
"""Тесты выбора тарифа: успех, ошибка БД (с отменой платежа), битый callback.

Типы mock-объектов намеренно Any — Pylance не умеет корректно
вычислять типы методов у MagicMock(spec=X) (видит их как MethodType
из spec-класса, а не как AsyncMock). В тестах это не важно, поэтому
Any — самый чистый способ без `# type: ignore` в каждой строке.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.types import CallbackQuery, Chat, Message, User

from handlers.payment import tariff_chosen


def _make_callback(data: str, user_id: int = 123) -> tuple[Any, Any]:
    """Возвращает (callback, message) с настроенными мок-методами.

    cb.answer, msg.edit_text, msg.answer — AsyncMock (awaitable).
    Прочие поля (id, from_user, chat) — MagicMock.
    """
    cb = MagicMock(spec=CallbackQuery)
    cb.data = data
    cb.id = "cb-1"

    user = MagicMock(spec=User)
    user.id = user_id
    cb.from_user = user
    cb.answer = AsyncMock()

    msg = MagicMock(spec=Message)
    msg.edit_text = AsyncMock()
    msg.answer = AsyncMock()
    chat = MagicMock(spec=Chat)
    chat.id = user_id
    msg.chat = chat

    cb.message = msg
    return cb, msg


def _make_async_session_ctx(
    session_obj=None, exit_exc=None
) -> tuple[Any, Any]:
    """Заменяет `async with AsyncSessionLocal() as session:`.

    Внутри `async with session.begin():` — тоже context manager.
    """
    if session_obj is None:
        session_obj = MagicMock()
        session_obj.add = MagicMock()

    begin_ctx = AsyncMock()
    begin_ctx.__aenter__ = AsyncMock(return_value=None)
    begin_ctx.__aexit__ = AsyncMock(return_value=None)
    session_obj.begin = MagicMock(return_value=begin_ctx)

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=session_obj)
    if exit_exc is not None:
        ctx.__aexit__ = AsyncMock(side_effect=exit_exc)
    else:
        ctx.__aexit__ = AsyncMock(return_value=None)
    return ctx, session_obj


@pytest.mark.asyncio
async def test_tariff_chosen_success():
    """Успех: платёж создан, запись в БД добавлена, edit_text с URL."""
    cb, msg = _make_callback("tariff_1m_rub", user_id=123)

    fake_payment = {
        "payment_id": "pay_123",
        "status": "pending",
        "confirmation_url": "https://yookassa.ru/confirm",
        "amount": "199.00",
    }

    ctx, session = _make_async_session_ctx()

    with patch("handlers.payment.yookassa_service") as mock_service, \
         patch("handlers.payment.AsyncSessionLocal", return_value=ctx):
        mock_service.create_payment = AsyncMock(return_value=fake_payment)

        await tariff_chosen(cb)

        mock_service.create_payment.assert_called_once()
        msg.edit_text.assert_awaited_once()
        session.add.assert_called_once()
        cb.answer.assert_awaited()


@pytest.mark.asyncio
async def test_tariff_chosen_payment_creation_fails():
    """create_payment вернул None — alert об ошибке, БД не трогаем."""
    cb, msg = _make_callback("tariff_1m_rub", user_id=123)

    ctx, session = _make_async_session_ctx()

    with patch("handlers.payment.yookassa_service") as mock_service, \
         patch("handlers.payment.AsyncSessionLocal", return_value=ctx):
        mock_service.create_payment = AsyncMock(return_value=None)

        await tariff_chosen(cb)

        session.add.assert_not_called()
        msg.edit_text.assert_not_awaited()
        cb.answer.assert_awaited()


@pytest.mark.asyncio
async def test_tariff_chosen_db_error_attempts_cancel():
    """Ошибка записи в БД — best-effort Payment.cancel, alert пользователю."""
    cb, msg = _make_callback("tariff_1m_rub", user_id=123)

    fake_payment = {
        "payment_id": "pay_123",
        "status": "pending",
        "confirmation_url": "https://yookassa.ru/confirm",
        "amount": "199.00",
    }

    ctx, _ = _make_async_session_ctx(exit_exc=RuntimeError("DB connection lost"))

    with patch("handlers.payment.yookassa_service") as mock_service, \
         patch("handlers.payment.AsyncSessionLocal", return_value=ctx), \
         patch("handlers.payment.log_error") as mock_log, \
         patch("yookassa.Payment.cancel", new_callable=MagicMock) as mock_cancel:
        mock_service.create_payment = AsyncMock(return_value=fake_payment)

        await tariff_chosen(cb)

        cb.answer.assert_awaited()
        msg.edit_text.assert_not_awaited()
        mock_log.assert_called()
        mock_cancel.assert_called_once()


@pytest.mark.asyncio
async def test_tariff_chosen_invalid_callback_data():
    """callback_data с недостаточным числом частей → ValidationError → alert."""
    cb, msg = _make_callback("tariff_bad", user_id=123)

    with patch("handlers.payment.yookassa_service") as mock_service:
        mock_service.create_payment = AsyncMock()

        await tariff_chosen(cb)

        mock_service.create_payment.assert_not_called()
        cb.answer.assert_awaited()


@pytest.mark.asyncio
async def test_tariff_chosen_invalid_period():
    """Неизвестный период → ValidationError."""
    cb, msg = _make_callback("tariff_99m_rub", user_id=123)

    with patch("handlers.payment.yookassa_service") as mock_service:
        mock_service.create_payment = AsyncMock()

        await tariff_chosen(cb)

        mock_service.create_payment.assert_not_called()
        cb.answer.assert_awaited()