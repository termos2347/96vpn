# utils/cache.py
"""In-memory кэш и rate limiting.

Используется как fallback, когда Redis недоступен (REDIS_ENABLED=false
или временная ошибка соединения). Всё хранится в памяти процесса и
сбрасывается при перезапуске бота.

Операции атомарны в пределах одного asyncio event loop, пока между
чтением и записью нет `await`. Для многопроцессного режима нужен
настоящий Redis.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

_cache: dict[str, tuple[Any, datetime]] = {}


def set_cache(key: str, value: Any, ttl_seconds: int = 300) -> None:
    """Сохранить значение в кэш на указанное количество секунд."""
    _cache[key] = (value, datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds))


def get_cache(key: str) -> Any | None:
    """Получить значение из кэша, если оно ещё не истекло."""
    entry = _cache.get(key)
    if entry:
        value, expires = entry
        if datetime.now(timezone.utc) < expires:
            return value
        # Удаляем просроченную запись
        del _cache[key]
    return None


def clear_cache(key: str | None = None) -> None:
    """Очистить весь кэш или конкретный ключ."""
    if key:
        _cache.pop(key, None)
    else:
        _cache.clear()


def rate_limit_check_memory(
    key: str, max_per_minute: int, expire: int = 60
) -> tuple[bool, int]:
    """In-memory rate limiting — fallback, когда Redis недоступен.

    Использует тот же формат ключа, что RedisService.rate_limit_check
    (incr + expire). Возвращает (allowed, current_count).

    Операция атомарна в asyncio (нет `await` между get и set),
    но не безопасна при многопроцессном запуске — для горизонтального
    масштабирования обязателен Redis.
    """
    now = datetime.now(timezone.utc)
    full_key = f"rl:{key}"
    entry = _cache.get(full_key)
    if entry:
        count, expires = entry
        if now < expires:
            count += 1
            _cache[full_key] = (count, expires)
            return count <= max_per_minute, count
    _cache[full_key] = (1, now + timedelta(seconds=expire))
    return 1 <= max_per_minute, 1


def clear_rate_limit_memory(key: str) -> None:
    """Сбросить счётчик rate limiting по ключу."""
    _cache.pop(f"rl:{key}", None)