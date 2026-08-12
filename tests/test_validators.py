import pytest

from utils.validators import (
    ValidationError,
    validate_currency,
    validate_days,
    validate_user_id,
    validate_uuid,
)


def test_validate_user_id():
    assert validate_user_id(123)
    with pytest.raises(ValidationError):
        validate_user_id(0)


def test_validate_days():
    assert validate_days(30)
    with pytest.raises(ValidationError):
        validate_days(10)


def test_validate_currency():
    assert validate_currency("rub")
    with pytest.raises(ValidationError):
        validate_currency("eur")


def test_validate_uuid():
    assert validate_uuid("123e4567-e89b-12d3-a456-426614174000")
    with pytest.raises(ValidationError):
        validate_uuid("invalid-uuid")
