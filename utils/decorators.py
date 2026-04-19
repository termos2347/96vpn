from functools import wraps
from aiogram.types import Message

def check_subscription(func):
    @wraps(func)
    async def wrapper(message: Message, *args, **kwargs):
        # Заглушка: всегда пропускаем
        return await func(message, *args, **kwargs)
    return wrapper