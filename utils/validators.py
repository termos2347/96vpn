"""Модуль для валидации входных данных."""
import logging
from typing import Optional
import re

logger = logging.getLogger(__name__)

class ValidationError(Exception):
    """Исключение валидации."""
    pass

def validate_user_id(user_id: int) -> bool:
    """Проверяет валидность user_id Telegram."""
    if not isinstance(user_id, int) or user_id < 1:
        raise ValidationError(f"Invalid user_id: {user_id}")
    return True

def validate_email(email: str) -> bool:
    """Проверяет валидность email."""
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(email_pattern, email):
        raise ValidationError(f"Invalid email: {email}")
    return True

def validate_days(days: int) -> bool:
    """Проверяет валидность количества дней подписки."""
    valid_days = [30, 90, 180]
    if days not in valid_days:
        raise ValidationError(f"Invalid days: {days}. Must be one of {valid_days}")
    return True

def validate_currency(currency: str) -> bool:
    """Проверяет валидность валюты."""
    valid_currencies = ["rub", "stars", "usdt"]
    if currency not in valid_currencies:
        raise ValidationError(f"Invalid currency: {currency}. Must be one of {valid_currencies}")
    return True

def validate_uuid(uuid: str) -> bool:
    """Проверяет валидность UUID."""
    uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    if not re.match(uuid_pattern, uuid.lower()):
        raise ValidationError(f"Invalid UUID: {uuid}")
    return True

def sanitize_email(email: str) -> str:
    """Санитизирует email для безопасного использования."""
    # Удаляем опасные символы, оставляем только буквы, цифры, точки, подчеркивания, дефисы
    return re.sub(r'[^a-zA-Z0-9._-]', '', email)

def sanitize_username(username: str) -> str:
    """Санитизирует username."""
    return re.sub(r'[^a-zA-Z0-9._-]', '', username)[:100]
