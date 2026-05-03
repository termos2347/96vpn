import jwt
from datetime import datetime, timedelta, timezone
from config import INTERNAL_API_SECRET
from handlers.payment import create_payment_token


def test_create_payment_token():
    token = create_payment_token(123, "vpn", "1m", "rub", 300)
    payload = jwt.decode(token, INTERNAL_API_SECRET, algorithms=["HS256"])

    assert payload["telegram_id"] == 123
    assert payload["product_type"] == "vpn"
    assert payload["period"] == "1m"
    assert payload["currency"] == "rub"
    assert payload["amount"] == 300
    assert "exp" in payload

    now = datetime.now(timezone.utc)
    exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
    assert exp > now
    assert exp < now + timedelta(hours=3)   # запас