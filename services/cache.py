import redis.asyncio as redis
import json
import logging

logger = logging.getLogger(__name__)

REDIS_URL = "redis://localhost:6379/0"

class CacheManager:
    def __init__(self):
        self.client = redis.from_url(REDIS_URL, decode_responses=True)

    async def get_prompts_data(self):
        cached = await self.client.get("prompts_data")
        if cached:
            return json.loads(cached)
        return None

    async def set_prompts_data(self, data):
        await self.client.set("prompts_data", json.dumps(data))
        logger.info("Prompts data cached in Redis")

    async def invalidate(self):
        await self.client.delete("prompts_data")
        logger.info("Prompts cache invalidated")

cache_manager = CacheManager()