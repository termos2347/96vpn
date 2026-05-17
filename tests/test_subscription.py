from datetime import datetime, timedelta, timezone
from web.services.auth import SubscriptionService
from db.models import WebUser


def test_days_remaining():
    user = WebUser()
    now = datetime.now(timezone.utc)
    # Добавляем 1 секунду, чтобы разница была чуть больше 5 дней
    user.expiry_date = now + timedelta(days=5, seconds=1)
    assert SubscriptionService.get_days_remaining(user) == 5


def test_days_remaining_none():
    user = WebUser()
    user.expiry_date = None
    assert SubscriptionService.get_days_remaining(user) is None


def test_days_remaining_expired():
    user = WebUser()
    user.expiry_date = datetime.now(timezone.utc) - timedelta(days=1)
    assert SubscriptionService.get_days_remaining(user) == 0