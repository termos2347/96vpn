"""
Гибридный кэш-сервис с автоматическим fallback:
- Если Redis доступен и указан REDIS_URL → используем Redis.
- Иначе → in-memory кэш (словарь).
"""
import json
import logging
from typing import Any, Optional

from config import settings

logger = logging.getLogger(__name__)


class HybridCache:
    def __init__(self):
        self._memory_cache: dict[str, Any] = {}
        self._redis_client = None
        self._is_redis_available = False

        redis_url = getattr(settings, 'REDIS_URL', None)
        if redis_url:
            try:
                import redis.asyncio as redis
                self._redis_client = redis.from_url(redis_url, decode_responses=True)
                self._is_redis_available = True
                logger.info("[INFO]Redis cache backend initialized (URL: %s)", redis_url)
            except Exception as e:
                logger.warning("Redis connection failed: %s. Falling back to in-memory cache.", e)
        else:
            logger.info("REDIS_URL not set. Using in-memory cache.")

    async def get(self, key: str) -> Optional[Any]:
        """Получить значение из кэша."""
        if self._is_redis_available:
            try:
                value = await self._redis_client.get(key)
                if value:
                    return json.loads(value)
            except Exception as e:
                logger.error("Redis GET error for key '%s': %s. Falling back to memory.", key, e)
        # fallback или Redis недоступен
        return self._memory_cache.get(key)

    async def set(self, key: str, value: Any, ttl_seconds: int = 300) -> None:
        """Сохранить значение в кэш с TTL (секунды)."""
        if self._is_redis_available:
            try:
                await self._redis_client.setex(key, ttl_seconds, json.dumps(value))
                return
            except Exception as e:
                logger.error("Redis SETEX error for key '%s': %s. Storing only in memory.", key, e)
        # fallback
        self._memory_cache[key] = value
        # В production можно добавить очистку по TTL, но для простоты оставим так

    async def delete(self, key: str) -> None:
        """Удалить ключ из кэша."""
        if self._is_redis_available:
            try:
                await self._redis_client.delete(key)
            except Exception as e:
                logger.error("Redis DELETE error for key '%s': %s", key, e)
        self._memory_cache.pop(key, None)

    async def clear(self) -> None:
        """Очистить весь кэш (осторожно, Redis FLUSHDB)."""
        if self._is_redis_available:
            try:
                await self._redis_client.flushdb()
                logger.warning("Redis cache flushed")
            except Exception as e:
                logger.error("Redis FLUSHDB error: %s", e)
        self._memory_cache.clear()


# Глобальный экземпляр (использовать во всём приложении)
cache = HybridCache()