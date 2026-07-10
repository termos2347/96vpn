# utils/decorators.py
from functools import wraps
from aiogram.types import Message, CallbackQuery
from datetime import datetime, timezone, timedelta
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)

# Rate limiting хранилище: {user_id: [timestamps]}
_user_actions = defaultdict(list)
RATE_LIMIT_SECONDS = 1  # 1 секунда между командами
RATE_LIMIT_THRESHOLD = 20  # 5 команд за 60 секунд
MAX_STORED_USERS = 10000  # максимальное количество пользователей в кэше

def rate_limit(max_per_minute: int = 5):
    """Декоратор для rate limiting команд пользователя."""
    def decorator(func):
        @wraps(func)
        async def wrapper(message_or_callback, *args, **kwargs):
            if isinstance(message_or_callback, Message):
                user_id = message_or_callback.from_user.id
                user_info = f"@{message_or_callback.from_user.username or 'unknown'}"
            elif isinstance(message_or_callback, CallbackQuery):
                user_id = message_or_callback.from_user.id
                user_info = f"@{message_or_callback.from_user.username or 'unknown'}"
            else:
                return await func(message_or_callback, *args, **kwargs)

            now = datetime.now(timezone.utc)
            cutoff_time = now - timedelta(seconds=60)

            # Чистим старые записи
            if user_id in _user_actions:
                filtered = [ts for ts in _user_actions[user_id] if ts > cutoff_time]
                if filtered:
                    _user_actions[user_id] = filtered
                else:
                    _user_actions.pop(user_id, None)

            # Ограничиваем общее количество записей, чтобы избежать утечек памяти
            if len(_user_actions) > MAX_STORED_USERS:
                # Удаляем половину самых старых записей (по ключам)
                keys_to_remove = list(_user_actions.keys())[:MAX_STORED_USERS // 2]
                for key in keys_to_remove:
                    _user_actions.pop(key, None)

            current_count = len(_user_actions.get(user_id, []))
            if current_count >= max_per_minute:
                logger.info(f"Rate limit exceeded for user {user_id} {user_info}")
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

            _user_actions[user_id].append(now)
            return await func(message_or_callback, *args, **kwargs)

        return wrapper
    return decorator