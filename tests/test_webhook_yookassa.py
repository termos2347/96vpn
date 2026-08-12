from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from db.models import BotPayment, BotUser
from services.payment_yookassa import YookassaService


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
        mock_manager.create_key = AsyncMock(return_value="https://test.com/sub/xyz")
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

        mock_manager.create_key.assert_called_once_with(telegram_id, 30)
        mock_bot.send_message.assert_called_once()


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
