# services/redis_service.py
import logging

import redis.asyncio as redis

from config import settings

logger = logging.getLogger(__name__)


class RedisService:
    _instance = None
    _client: redis.Redis | None = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    async def connect(self):
        if self._client is not None:
            return

        try:
            if settings.REDIS_URL:
                url = settings.REDIS_URL
                if url.startswith("redis://") and not url.startswith("rediss://"):
                    url = url.replace("redis://", "rediss://", 1)
                    settings.REDIS_URL = url

                self._client = redis.Redis.from_url(
                    url,
                    decode_responses=True,
                    socket_connect_timeout=3,
                    socket_timeout=3,
                )
                # Маскируем пароль для лога
                display_url = url.split("@")[-1] if "@" in url else url
            else:
                self._client = redis.Redis(
                    host=settings.REDIS_HOST,
                    port=settings.REDIS_PORT,
                    db=settings.REDIS_DB,
                    password=settings.REDIS_PASSWORD or None,
                    decode_responses=True,
                    socket_connect_timeout=3,
                    socket_timeout=3,
                )
                display_url = f"{settings.REDIS_HOST}:{settings.REDIS_PORT}"

            await self._client.ping()
            logger.info(f"✅ Connected to Redis at {display_url}")
        except Exception as e:
            logger.error(f"❌ Redis connection failed: {e}")
            self._client = None

    async def close(self):
        if self._client:
            await self._client.close()
            logger.info("Redis connection closed")

    @property
    def client(self) -> redis.Redis:
        if self._client is None:
            raise RuntimeError("Redis not connected")
        return self._client

    async def set_cache(self, key: str, value: str, ttl: int = None) -> bool:
        if self._client is None:
            return False
        try:
            if ttl is None:
                ttl = settings.REDIS_CACHE_TTL
            await self.client.setex(key, ttl, value)
            return True
        except Exception as e:
            logger.error(f"Redis set_cache error: {e}")
            return False

    async def get_cache(self, key: str) -> str | None:
        if self._client is None:
            return None
        try:
            return await self.client.get(key)
        except Exception as e:
            logger.error(f"Redis get_cache error: {e}")
            return None

    async def delete_cache(self, key: str) -> bool:
        if self._client is None:
            return False
        try:
            await self.client.delete(key)
            return True
        except Exception as e:
            logger.error(f"Redis delete_cache error: {e}")
            return False

    async def rate_limit_check(self, key: str, max_per_minute: int, expire: int = 60):
        if self._client is None:
            return True, 0
        try:
            count = await self.client.incr(key)
            if count == 1:
                await self.client.expire(key, expire)
            current_count = int(count)
            return current_count <= max_per_minute, current_count
        except Exception as e:
            logger.error(f"Redis rate_limit_check error: {e}")
            return True, 0

    async def clear_rate_limit(self, key: str) -> bool:
        if self._client is None:
            return False
        try:
            await self.client.delete(key)
            return True
        except Exception as e:
            logger.error(f"Redis clear_rate_limit error: {e}")
            return False


redis_service = RedisService()
