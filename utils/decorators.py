# utils/decorators.py
from functools import wraps
from aiogram.types import Message, CallbackQuery
from datetime import datetime, timezone, timedelta
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)

# Структура: {user_id: {func_name: [timestamps]}}
_user_actions = defaultdict(lambda: defaultdict(list))
RATE_LIMIT_SECONDS = 1  # минимальный интервал между вызовами (можно не использовать)
MAX_STORED_USERS = 10000

def rate_limit(max_per_minute: int = 5):
    """Декоратор для ограничения частоты вызовов конкретной функции для одного пользователя."""
    def decorator(func):
        @wraps(func)
        async def wrapper(message_or_callback, *args, **kwargs):
            # Определяем user_id
            if isinstance(message_or_callback, Message):
                user_id = message_or_callback.from_user.id
            elif isinstance(message_or_callback, CallbackQuery):
                user_id = message_or_callback.from_user.id
            else:
                return await func(message_or_callback, *args, **kwargs)

            func_name = func.__name__
            now = datetime.now(timezone.utc)
            cutoff_time = now - timedelta(seconds=60)

            # Получаем список временных меток для данного пользователя и функции
            timestamps = _user_actions[user_id][func_name]

            # Оставляем только те, что за последние 60 секунд
            filtered = [ts for ts in timestamps if ts > cutoff_time]
            _user_actions[user_id][func_name] = filtered

            # Проверяем лимит
            if len(filtered) >= max_per_minute:
                logger.info(f"Rate limit exceeded for user {user_id} on function {func_name}")
                if isinstance(message_or_callback, Message):
                    await message_or_callback.answer(
                        "⏱️ Слишком много запросов. Подождите немного..."
                    )
                elif isinstance(message_or_callback, CallbackQuery):
                    await message_or_callback.answer(
                        "⏱️ Слишком много запросов. Подождите немного...",
                        show_alert=False
                    )
                return

            # Добавляем текущую метку
            _user_actions[user_id][func_name].append(now)

            # Ограничение по общему количеству пользователей в кэше (защита от утечек)
            if len(_user_actions) > MAX_STORED_USERS:
                # Удаляем половину самых старых записей
                keys_to_remove = list(_user_actions.keys())[:MAX_STORED_USERS // 2]
                for key in keys_to_remove:
                    del _user_actions[key]

            return await func(message_or_callback, *args, **kwargs)

        return wrapper
    return decorator