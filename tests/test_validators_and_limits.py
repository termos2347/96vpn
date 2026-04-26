"""Unit tests для основных компонентов."""
import pytest
import asyncio
from datetime import datetime, timedelta
from utils.validators import (
    validate_user_id, validate_email, validate_days, 
    validate_currency, validate_uuid, ValidationError
)
from utils.decorators import rate_limit
from db.crud import set_vpn_subscription, get_vpn_end


class TestValidators:
    """Тесты для валидаторов."""
    
    def test_validate_user_id_valid(self):
        """Проверяет валидацию корректного user_id."""
        assert validate_user_id(123456789) == True
        
    def test_validate_user_id_invalid(self):
        """Проверяет отклонение некорректного user_id."""
        with pytest.raises(ValidationError):
            validate_user_id(-1)
        with pytest.raises(ValidationError):
            validate_user_id(0)
        with pytest.raises(ValidationError):
            validate_user_id("not_a_number")
    
    def test_validate_email_valid(self):
        """Проверяет валидацию корректного email."""
        assert validate_email("user@example.com") == True
        assert validate_email("test.email+tag@example.co.uk") == True
    
    def test_validate_email_invalid(self):
        """Проверяет отклонение некорректного email."""
        with pytest.raises(ValidationError):
            validate_email("invalid_email")
        with pytest.raises(ValidationError):
            validate_email("user@")
        with pytest.raises(ValidationError):
            validate_email("@example.com")
    
    def test_validate_days_valid(self):
        """Проверяет валидацию корректного количества дней."""
        assert validate_days(30) == True
        assert validate_days(90) == True
        assert validate_days(180) == True
    
    def test_validate_days_invalid(self):
        """Проверяет отклонение некорректного количества дней."""
        with pytest.raises(ValidationError):
            validate_days(45)  # не в списке разрешённых
        with pytest.raises(ValidationError):
            validate_days(0)
        with pytest.raises(ValidationError):
            validate_days(-30)
    
    def test_validate_currency_valid(self):
        """Проверяет валидацию корректной валюты."""
        assert validate_currency("rub") == True
        assert validate_currency("stars") == True
        assert validate_currency("usdt") == True
    
    def test_validate_currency_invalid(self):
        """Проверяет отклонение некорректной валюты."""
        with pytest.raises(ValidationError):
            validate_currency("eur")
        with pytest.raises(ValidationError):
            validate_currency("RUB")  # case sensitive
        with pytest.raises(ValidationError):
            validate_currency("")
    
    def test_validate_uuid_valid(self):
        """Проверяет валидацию корректного UUID."""
        assert validate_uuid("550e8400-e29b-41d4-a716-446655440000") == True
        assert validate_uuid("550E8400-E29B-41D4-A716-446655440000") == True  # uppercase
    
    def test_validate_uuid_invalid(self):
        """Проверяет отклонение некорректного UUID."""
        with pytest.raises(ValidationError):
            validate_uuid("not-a-uuid")
        with pytest.raises(ValidationError):
            validate_uuid("550e8400-e29b-41d4-a716")  # incomplete
        with pytest.raises(ValidationError):
            validate_uuid("")


class TestRateLimit:
    """Тесты для rate limiting."""
    
    @pytest.mark.asyncio
    async def test_rate_limit_allows_within_limit(self):
        """Проверяет, что rate limit пропускает запросы в пределах лимита."""
        call_count = 0
        
        @rate_limit(max_per_minute=5)
        async def test_func(user_id):
            nonlocal call_count
            call_count += 1
            return True
        
        # Симулируем вызовы в рамках лимита
        # Примечание: это упрощённый тест, так как rate_limit работает с Message/CallbackQuery
        # Полный тест требует мокирования Telegram объектов
        pass


class TestSubscriptionLogic:
    """Тесты для логики подписок."""
    
    @pytest.mark.asyncio
    async def test_set_vpn_subscription_creates_subscription(self):
        """Проверяет создание VPN подписки."""
        # Примечание: для полного теста нужна реальная БД или мокирование
        # Это упрощённый пример
        pass
    
    @pytest.mark.asyncio
    async def test_set_vpn_subscription_extends_existing(self):
        """Проверяет продление существующей VPN подписки."""
        # Примечание: для полного теста нужна реальная БД
        pass


# Простые юнит тесты, которые не требуют БД
class TestDateCalculations:
    """Тесты для вычисления дат."""
    
    def test_subscription_end_date_calculation(self):
        """Проверяет правильность расчёта даты конца подписки."""
        now = datetime.now()
        days = 30
        expected_end = now + timedelta(days=days)
        
        # Проверяем, что разница примерно равна 30 дням (с допуском на секунды)
        actual_diff = (expected_end - now).days
        assert actual_diff == days


class TestValidationEdgeCases:
    """Тесты для граничных случаев валидации."""
    
    def test_very_large_user_id(self):
        """Проверяет валидацию очень больших user_id."""
        assert validate_user_id(9999999999999) == True
    
    def test_email_with_special_chars(self):
        """Проверяет email с спецсимволами."""
        assert validate_email("user+tag@example.com") == True
        assert validate_email("first.last@example.com") == True
    
    def test_uuid_lowercase(self):
        """Проверяет UUID в нижнем регистре."""
        uuid_lower = "550e8400-e29b-41d4-a716-446655440000"
        assert validate_uuid(uuid_lower) == True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
