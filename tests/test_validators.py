import pytest
from utils.validators import validate_user_id, validate_email, validate_days, validate_currency, ValidationError

def test_validate_user_id():
    assert validate_user_id(123)
    with pytest.raises(ValidationError):
        validate_user_id(0)

def test_validate_email():
    assert validate_email("user@example.com")
    with pytest.raises(ValidationError):
        validate_email("invalid")

def test_validate_days():
    assert validate_days(30)
    with pytest.raises(ValidationError):
        validate_days(10)

def test_validate_currency():
    assert validate_currency("rub")
    with pytest.raises(ValidationError):
        validate_currency("eur")