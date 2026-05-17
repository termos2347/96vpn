import logging
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from config import settings
from web.security import get_current_user_optional

logger = logging.getLogger(__name__)


async def get_user_or_ip(request: Request) -> str:
    """
    Ключ для rate limiting:
    - если пользователь авторизован – используем его ID
    - иначе – IP-адрес
    """
    user = await get_current_user_optional(request)
    if user:
        return f"user_{user.id}"
    return get_remote_address(request)


# Пытаемся получить URL для Redis из переменных окружения
storage_uri = getattr(settings, 'RATE_LIMIT_STORAGE_URI', None)

if storage_uri:
    # Используем Redis (slowapi поддерживает async+redis)
    limiter = Limiter(key_func=get_user_or_ip, storage_uri=storage_uri)
    logger.info("Rate limiter configured with Redis backend: %s", storage_uri)
else:
    # In-memory storage по умолчанию (для разработки)
    limiter = Limiter(key_func=get_user_or_ip)
    logger.info("INFO: Rate limiter configured with in-memory storage.")