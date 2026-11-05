# tests/test_security.py
"""Тесты безопасности: шифрование, IP-фильтр, rate limiting, memory fallback."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.types import CallbackQuery, Message, User

from config import settings
from internal_api import ip_in_network
from services.redis_service import redis_service
from utils.cache import get_cache, rate_limit_check_memory, set_cache
from utils.decorators import rate_limit
from utils.encryption import decrypt_password, encrypt_password, is_encrypted

# ============================================================
# Шифрование
# ============================================================


def test_encryption():
    original = "my_secret_password"
    encrypted = encrypt_password(original)
    assert encrypted != original
    assert is_encrypted(encrypted)
    assert decrypt_password(encrypted) == original


def test_encryption_empty():
    assert encrypt_password("") == ""
    assert decrypt_password("") == ""
    assert is_encrypted("") is False


def test_encryption_plain_text_auto_decrypt():
    plain = "not_encrypted"
    assert decrypt_password(plain) == plain


# ============================================================
# IP-фильтр ЮKassa
# ============================================================


@pytest.fixture
def trusted_ips(monkeypatch):
    ips = [
        "185.71.76.0/24",
        "185.71.77.0/24",
        "77.75.153.0/25",
        "77.75.154.128/25",
        "77.75.156.11",
        "77.75.156.35",
        "2a02:5180::/32",
        "127.0.0.1",
    ]
    monkeypatch.setattr(settings, "YOOKASSA_TRUSTED_IPS", ips)
    return ips


def test_ipv4_in_cidr(trusted_ips):
    assert ip_in_network("185.71.76.5") is True
    assert ip_in_network("185.71.76.255") is True
    assert ip_in_network("185.71.77.100") is True


def test_ipv4_not_in_cidr(trusted_ips):
    assert ip_in_network("185.71.78.5") is False
    assert ip_in_network("10.0.0.1") is False


def test_exact_ip(trusted_ips):
    assert ip_in_network("77.75.156.11") is True
    assert ip_in_network("77.75.156.35") is True
    assert ip_in_network("77.75.156.12") is False


def test_half_cidr(trusted_ips):
    assert ip_in_network("77.75.153.0") is True
    assert ip_in_network("77.75.153.127") is True
    assert ip_in_network("77.75.153.128") is False


def test_ipv6_in_ipv6_cidr(trusted_ips):
    assert ip_in_network("2a02:5180::1") is True
    assert ip_in_network("2a02:5180:ffff::1") is True


def test_ipv6_not_in_ipv6_cidr(trusted_ips):
    assert ip_in_network("2a02:5181::1") is False


def test_ipv4_not_confused_with_ipv6(trusted_ips):
    assert ip_in_network("127.0.0.1") is True
    assert ip_in_network("::1") is False


def test_invalid_ip_string(trusted_ips):
    assert ip_in_network("not-an-ip") is False
    assert ip_in_network("") is False
    assert ip_in_network("999.999.999.999") is False


def test_malformed_cidr_does_not_crash(monkeypatch):
    monkeypatch.setattr(
        settings, "YOOKASSA_TRUSTED_IPS", ["1.2.3.4/24", "185.71.76.0/24"]
    )
    assert ip_in_network("1.2.3.5") is True
    assert ip_in_network("1.2.4.5") is False
    assert ip_in_network("185.71.76.5") is True


def test_garbage_cidr_ignored(monkeypatch):
    monkeypatch.setattr(
        settings, "YOOKASSA_TRUSTED_IPS", ["not-a-cidr", "185.71.76.0/24"]
    )
    assert ip_in_network("185.71.76.5") is True
    assert ip_in_network("10.0.0.1") is False


# ============================================================
# Rate limiting
# ============================================================


def make_message(user_id: int, username: str = "test") -> Any:
    msg = MagicMock(spec=Message)
    msg.from_user = MagicMock(spec=User)
    msg.from_user.id = user_id
    msg.from_user.username = username
    msg.answer = AsyncMock()
    return msg


@pytest.mark.asyncio
async def test_rate_limit_allows_first_call():
    message = make_message(123)
    called = False

    @rate_limit(max_per_minute=3)
    async def handler(msg):
        nonlocal called
        called = True

    with patch("utils.decorators.redis_service") as mock_redis:
        mock_redis.rate_limit_check = AsyncMock(return_value=(True, 1))
        await handler(message)

    assert called is True


@pytest.mark.asyncio
async def test_rate_limit_blocks_excessive_calls():
    message = make_message(456, "spammer")

    @rate_limit(max_per_minute=2)
    async def handler(msg):
        return "ok"

    with patch("utils.decorators.redis_service") as mock_redis:
        mock_redis.rate_limit_check = AsyncMock(
            side_effect=[(True, 1), (True, 2), (False, 3)]
        )
        assert await handler(message) == "ok"
        assert await handler(message) == "ok"
        assert await handler(message) is None

    message.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_rate_limit_fail_open_on_redis_error():
    message = make_message(789, "resetter")

    @rate_limit(max_per_minute=1)
    async def handler(msg):
        return "ok"

    with patch("utils.decorators.redis_service") as mock_redis:
        mock_redis.rate_limit_check = AsyncMock(
            side_effect=RuntimeError("Redis not connected")
        )
        result = await handler(message)

    assert result == "ok"


@pytest.mark.asyncio
async def test_rate_limit_skips_anonymous():
    message = make_message(0)
    message.from_user = None

    @rate_limit(max_per_minute=1)
    async def handler(msg):
        return "ok"

    with patch("utils.decorators.redis_service") as mock_redis:
        mock_redis.rate_limit_check = AsyncMock(return_value=(True, 1))
        result = await handler(message)

    assert result == "ok"
    mock_redis.rate_limit_check.assert_not_awaited()


@pytest.mark.asyncio
async def test_rate_limit_callback_query():
    cb = MagicMock(spec=CallbackQuery)
    cb.from_user = MagicMock(spec=User)
    cb.from_user.id = 999
    cb.answer = AsyncMock()

    @rate_limit(max_per_minute=1)
    async def handler(c):
        return "ok"

    with patch("utils.decorators.redis_service") as mock_redis:
        mock_redis.rate_limit_check = AsyncMock(return_value=(False, 2))
        result = await handler(cb)

    assert result is None
    cb.answer.assert_awaited_once_with(
        "⏱️ Слишком много запросов. Подождите немного...", show_alert=False
    )


# ============================================================
# Memory fallback
# ============================================================


@pytest.mark.asyncio
async def test_redis_rate_limit_raises_when_disconnected(monkeypatch):
    monkeypatch.setattr(redis_service, "_client", None)
    with pytest.raises(RuntimeError, match="Redis not connected"):
        await redis_service.rate_limit_check("k", 5)


def test_memory_rate_limit():
    allowed, count = rate_limit_check_memory("test", 2)
    assert allowed is True and count == 1
    allowed, count = rate_limit_check_memory("test", 2)
    assert allowed is True and count == 2
    allowed, count = rate_limit_check_memory("test", 2)
    assert allowed is False and count == 3


def test_memory_cache_ttl_behavior():
    set_cache("k", "v", ttl_seconds=10)
    assert get_cache("k") == "v"
