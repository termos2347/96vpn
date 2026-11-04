# tests/test_memory_fallback.py
import pytest

from services.redis_service import redis_service
from utils.cache import get_cache, rate_limit_check_memory


@pytest.mark.asyncio
async def test_redis_rate_limit_raises_when_disconnected(monkeypatch):
    """При отключённом Redis rate_limit_check бросает, а не глотает ошибку."""
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
    from utils.cache import set_cache, get_cache

    set_cache("k", "v", ttl_seconds=10)
    assert get_cache("k") == "v"