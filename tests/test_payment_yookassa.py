from unittest.mock import MagicMock, patch

import pytest

from services.payment_yookassa import YookassaService


@pytest.mark.asyncio
async def test_create_payment_success():
    with patch("services.payment_yookassa.Payment.create") as mock_create:
        mock_payment = MagicMock()
        mock_payment.id = "pay_123"
        mock_payment.status = "pending"
        mock_payment.confirmation = MagicMock()
        mock_payment.confirmation.confirmation_url = "https://yookassa.ru/confirm"
        mock_create.return_value = mock_payment

        service = YookassaService()
        result = await service.create_payment(100, "test", {"source": "bot"})

        assert result is not None
        assert result["payment_id"] == "pay_123"
        assert result["confirmation_url"] == "https://yookassa.ru/confirm"
