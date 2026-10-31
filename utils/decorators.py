# utils/decorators.py
import logging
from functools import wraps

from aiogram.types import CallbackQuery, Message

from services.redis_service import redis_service

logger = logging.getLogger(__name__)


def rate_limit(max_per_minute: int = 5):
    """Декоратор для ограничения частоты вызовов функции (через Redis)."""

    def decorator(func):
        @wraps(func)
        async def wrapper(message_or_callback, *args, **kwargs):
            # Определяем user_id (только для Message / CallbackQuery)
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

            try:
                allowed, count = await redis_service.rate_limit_check(
                    key, max_per_minute
                )
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
            except Exception as e:
                # Redis недоступен — fail-open, чтобы бот не падал
                logger.warning(f"Rate limit check failed, skipping: {e}")

            return await func(message_or_callback, *args, **kwargs)

        return wrapper

    return decorator