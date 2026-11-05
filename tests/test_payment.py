# tests/test_payments.py
"""Тесты платежей: создание, выбор тарифа, вебхуки ЮKassa."""

import asyncio
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.types import CallbackQuery, Chat, Message, User
from sqlalchemy import select

from db.models import BotPayment, BotUser
from handlers.payment import tariff_chosen
from services import payment_yookassa as yk
from services.payment_yookassa import YookassaService


# ============================================================
# create_payment
# ============================================================


@pytest.mark.asyncio
async def test_create_payment_success():
    with patch("services.payment_yookassa.Payment.create") as mock_create:
        mock_payment = MagicMock()
        mock_payment.id = "pay_123"
        mock_payment.status = "pending"
        mock_payment.confirmation = MagicMock()
        mock_payment.confirmation.confirmation_url = "https://yookassa.ru/confirm"
        mock_payment.amount = MagicMock(value="100.00", currency="RUB")
        mock_create.return_value = mock_payment

        service = YookassaService()
        result = await service.create_payment(100, "test", {"source": "bot"})

        assert result is not None
        assert result["payment_id"] == "pay_123"
        assert result["confirmation_url"] == "https://yookassa.ru/confirm"


# ============================================================
# tariff_chosen
# ============================================================


def _make_callback(data: str, user_id: int = 123) -> tuple[Any, Any]:
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


def _make_async_session_ctx(session_obj=None, exit_exc=None) -> tuple[Any, Any]:
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
    cb, msg = _make_callback("tariff_bad", user_id=123)
    with patch("handlers.payment.yookassa_service") as mock_service:
        mock_service.create_payment = AsyncMock()
        await tariff_chosen(cb)
        mock_service.create_payment.assert_not_called()
        cb.answer.assert_awaited()


@pytest.mark.asyncio
async def test_tariff_chosen_invalid_period():
    cb, msg = _make_callback("tariff_99m_rub", user_id=123)
    with patch("handlers.payment.yookassa_service") as mock_service:
        mock_service.create_payment = AsyncMock()
        await tariff_chosen(cb)
        mock_service.create_payment.assert_not_called()
        cb.answer.assert_awaited()


# ============================================================
# Webhook YooKassa
# ============================================================


@pytest.mark.asyncio
async def test_webhook_success(test_session, mock_bot, mock_yookassa_payment):
    payment_id = "test_payment_success"
    telegram_id = 123456
    async with test_session.begin():
        payment = BotPayment(
            payment_id=payment_id,
            telegram_id=telegram_id,
            amount=100.00,
            currency="RUB",
            status="pending",
            is_paid=False,
        )
        test_session.add(payment)
        user = BotUser(telegram_id=telegram_id)
        test_session.add(user)

    mock_payment_obj = MagicMock()
    mock_payment_obj.id = payment_id
    mock_payment_obj.status = "succeeded"
    mock_payment_obj.amount = MagicMock(value="100.00", currency="RUB")
    mock_payment_obj.metadata = {
        "telegram_id": str(telegram_id),
        "product_type": "vpn",
        "period": "1m",
    }
    mock_yookassa_payment.find_one.return_value = mock_payment_obj

    with patch("services.payment_yookassa.get_vpn_manager") as mock_get_manager:
        mock_manager = AsyncMock()
        mock_manager.get_or_create_link = AsyncMock(
            return_value="https://test.com/sub/xyz"
        )
        mock_get_manager.return_value = mock_manager

        webhook_data = {"event": "payment.succeeded", "object": {"id": payment_id}}
        service = YookassaService()
        result = await service.process_webhook(webhook_data, test_session, mock_bot)

        assert result is True

        stmt = select(BotPayment).where(BotPayment.payment_id == payment_id)
        db_payment = (await test_session.execute(stmt)).scalar_one()
        assert db_payment.is_paid is True
        assert db_payment.status == "succeeded"

        stmt_user = select(BotUser).where(BotUser.telegram_id == telegram_id)
        user = (await test_session.execute(stmt_user)).scalar_one()
        assert user.vpn_subscription_end is not None
        assert user.vpn_subscription_end > datetime.now(timezone.utc)

        # Дожидаемся фоновой задачи создания ключа.
        # Раньше здесь был await asyncio.sleep(0), который НЕ гарантирует
        # запуск task — на медленном CI тест был flaky.
        if yk._pending_key_tasks:
            await asyncio.gather(*yk._pending_key_tasks, return_exceptions=True)

        assert mock_bot.send_message.call_count == 2

        activation_call = mock_bot.send_message.call_args_list[0]
        assert activation_call.args[0] == telegram_id
        assert "подписка" in activation_call.args[1].lower()

        key_call = mock_bot.send_message.call_args_list[1]
        assert key_call.args[0] == telegram_id
        assert "https://test.com/sub/xyz" in key_call.args[1]


@pytest.mark.asyncio
async def test_webhook_duplicate(test_session, mock_bot, mock_yookassa_payment):
    payment_id = "test_duplicate"
    telegram_id = 123
    async with test_session.begin():
        payment = BotPayment(
            payment_id=payment_id,
            telegram_id=telegram_id,
            amount=100.00,
            currency="RUB",
            status="succeeded",
            is_paid=True,
        )
        test_session.add(payment)

    webhook_data = {"event": "payment.succeeded", "object": {"id": payment_id}}
    service = YookassaService()
    result = await service.process_webhook(webhook_data, test_session, mock_bot)
    assert result is True

    stmt = select(BotPayment).where(BotPayment.payment_id == payment_id)
    db_payment = (await test_session.execute(stmt)).scalar_one()
    assert db_payment.is_paid is True


@pytest.mark.asyncio
async def test_webhook_missing_metadata(test_session, mock_bot, mock_yookassa_payment):
    payment_id = "test_no_meta"
    telegram_id = 123
    async with test_session.begin():
        payment = BotPayment(
            payment_id=payment_id,
            telegram_id=telegram_id,
            amount=100.00,
            currency="RUB",
            status="pending",
            is_paid=False,
        )
        test_session.add(payment)

    mock_payment_obj = MagicMock()
    mock_payment_obj.id = payment_id
    mock_payment_obj.status = "succeeded"
    mock_payment_obj.amount = MagicMock(value="100.00", currency="RUB")
    mock_payment_obj.metadata = {}
    mock_yookassa_payment.find_one.return_value = mock_payment_obj

    webhook_data = {"event": "payment.succeeded", "object": {"id": payment_id}}
    service = YookassaService()
    result = await service.process_webhook(webhook_data, test_session, mock_bot)
    assert result is False

    stmt = select(BotPayment).where(BotPayment.payment_id == payment_id)
    db_payment = (await test_session.execute(stmt)).scalar_one()
    assert db_payment.is_paid is False


@pytest.mark.asyncio
async def test_webhook_amount_mismatch(test_session, mock_bot, mock_yookassa_payment):
    payment_id = "test_amount_mismatch"
    telegram_id = 123
    async with test_session.begin():
        payment = BotPayment(
            payment_id=payment_id,
            telegram_id=telegram_id,
            amount=150.00,
            currency="RUB",
            status="pending",
            is_paid=False,
        )
        test_session.add(payment)

    mock_payment_obj = MagicMock()
    mock_payment_obj.id = payment_id
    mock_payment_obj.status = "succeeded"
    mock_payment_obj.amount = MagicMock(value="100.00", currency="RUB")
    mock_payment_obj.metadata = {
        "telegram_id": str(telegram_id),
        "product_type": "vpn",
        "period": "1m",
    }
    mock_yookassa_payment.find_one.return_value = mock_payment_obj

    webhook_data = {"event": "payment.succeeded", "object": {"id": payment_id}}
    service = YookassaService()
    result = await service.process_webhook(webhook_data, test_session, mock_bot)
    assert result is False

    stmt = select(BotPayment).where(BotPayment.payment_id == payment_id)
    db_payment = (await test_session.execute(stmt)).scalar_one()
    assert db_payment.is_paid is False