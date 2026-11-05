# utils/decorators.py
import logging
from functools import wraps

from aiogram.types import CallbackQuery, Message

from services.redis_service import redis_service
from utils.cache import rate_limit_check_memory

logger = logging.getLogger(__name__)


def rate_limit(max_per_minute: int = 5):
    """Декоратор для ограничения частоты вызовов функции.

    Основной бэкенд — Redis (работает между процессами и рестартами).
    Если Redis недоступен — автоматический fallback на in-memory
    (utils/cache.py). Лимит продолжает работать, но сбрасывается
    при перезапуске процесса.
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(message_or_callback, *args, **kwargs):
            if not isinstance(message_or_callback, (Message, CallbackQuery)):
                return await func(message_or_callback, *args, **kwargs)

            user = message_or_callback.from_user
            if user is None:
                # Анонимный админ канала или сервисное обновление —
                # не можем привязать лимит к пользователю, пропускаем.
                return await func(message_or_callback, *args, **kwargs)

            user_id = user.id
            func_name = func.__name__
            key = f"rl:{user_id}:{func_name}"

            allowed: bool
            count: int
            try:
                allowed, count = await redis_service.rate_limit_check(
                    key, max_per_minute
                )
            except Exception as e:
                # Redis отключён или упал — не пропускаем всё подряд,
                # а используем in-memory счётчик как fallback.
                logger.info(
                    f"Rate limit: Redis unavailable, using memory fallback "
                    f"({type(e).__name__}: {e})"
                )
                allowed, count = rate_limit_check_memory(key, max_per_minute)

            if not allowed:
                logger.info(
                    f"Rate limit exceeded for user {user_id} on {func_name} "
                    f"({count}/{max_per_minute})"
                )
                if isinstance(message_or_callback, Message):
                    await message_or_callback.answer(
                        "⏱️ Слишком много запросов. Подождите немного..."
                    )
                else:  # CallbackQuery
                    await message_or_callback.answer(
                        "⏱️ Слишком много запросов. Подождите немного...",
                        show_alert=False,
                    )
                return

            return await func(message_or_callback, *args, **kwargs)

        return wrapper

    return decorator
