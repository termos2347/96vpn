from datetime import datetime, timedelta, timezone
from typing import Any

_cache: dict[str, tuple[Any, datetime]] = {}


def set_cache(key: str, value: Any, ttl_seconds: int = 300):
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


def clear_cache(key: str | None = None):
    """Очистить весь кэш или конкретный ключ."""
    if key:
        _cache.pop(key, None)
    else:
        _cache.clear()
