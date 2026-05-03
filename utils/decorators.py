from functools import wraps
from aiogram.types import Message, CallbackQuery
from datetime import datetime, timedelta
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)

# Rate limiting хранилище: {user_id: [timestamps]}
_user_actions = defaultdict(list)
RATE_LIMIT_SECONDS = 1  # 1 секунда между командами
RATE_LIMIT_THRESHOLD = 5  # 5 команд за 60 секунд

def check_subscription(func):
    @wraps(func)
    async def wrapper(message: Message, *args, **kwargs):
        # Заглушка: всегда пропускаем
        return await func(message, *args, **kwargs)
    return wrapper

def rate_limit(max_per_minute: int = 5):
    """Декоратор для rate limiting команд пользователя."""
    def decorator(func):
        @wraps(func)
        async def wrapper(message_or_callback, *args, **kwargs):
            # Получаем user_id и текущее время
            if isinstance(message_or_callback, Message):
                user_id = message_or_callback.from_user.id
                user_info = f"@{message_or_callback.from_user.username or 'unknown'}"
            elif isinstance(message_or_callback, CallbackQuery):
                user_id = message_or_callback.from_user.id
                user_info = f"@{message_or_callback.from_user.username or 'unknown'}"
            else:
                return await func(message_or_callback, *args, **kwargs)
            
            now = datetime.now()
            cutoff_time = now - timedelta(seconds=1)
            
            # Чистим старые записи
            _user_actions[user_id] = [
                ts for ts in _user_actions[user_id] if ts > cutoff_time
            ]
            
            # Проверяем лимит
            if len(_user_actions[user_id]) >= max_per_minute:
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
            
            # Добавляем новую запись
            _user_actions[user_id].append(now)
            
            # Вызываем функцию
            return await func(message_or_callback, *args, **kwargs)
        
        return wrapper
    return decorator