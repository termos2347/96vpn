from slowapi import Limiter
from slowapi.util import get_remote_address
from fastapi import Request
from web.security import get_current_user_optional

async def get_user_or_ip(request: Request):
    """
    Ключ для rate limiting:
    - если пользователь авторизован – используем его ID
    - иначе – IP-адрес
    """
    user = await get_current_user_optional(request)
    if user:
        return f"user_{user.id}"
    return get_remote_address(request)

limiter = Limiter(key_func=get_user_or_ip, default_limits=["100/hour"])