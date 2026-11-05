# utils/cache.py
"""In-memory кэш и rate limiting.

Используется как fallback, когда Redis недоступен (REDIS_ENABLED=false
или временная ошибка соединения). Всё хранится в памяти процесса и
сбрасывается при перезапуске бота.

BUGFIX: rate-limit вынесен в отдельный словарь _rl_cache, чтобы
переполнение основного кэша (ссылок/прочего) не выкидывало счётчики
лимитов и не «разрешало» лишние вызовы.

Операции атомарны в пределах одного asyncio event loop, пока между
чтением и записью нет `await`. Для многопроцессного режима нужен
настоящий Redis.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

_MAX_CACHE_SIZE = 10_000
_RL_MAX_SIZE = 10_000

_cache: dict[str, tuple[Any, datetime]] = {}
_rl_cache: dict[str, tuple[int, datetime]] = {}


def _cleanup_expired(now: datetime) -> None:
    for k in [k for k, (_, exp) in _cache.items() if now >= exp]:
        _cache.pop(k, None)


def _rl_cleanup_expired(now: datetime) -> None:
    for k in [k for k, (_, exp) in _rl_cache.items() if now >= exp]:
        _rl_cache.pop(k, None)


def set_cache(key: str, value: Any, ttl_seconds: int = 300) -> None:
    """Сохранить значение в кэш на указанное количество секунд."""
    now = datetime.now(timezone.utc)
    if len(_cache) >= _MAX_CACHE_SIZE:
        _cleanup_expired(now)
        if len(_cache) >= _MAX_CACHE_SIZE:
            logger.warning(
                f"Memory cache exceeded {_MAX_CACHE_SIZE} entries "
                f"({len(_cache)}), dropping oldest ~10%"
            )
            drop = max(1, _MAX_CACHE_SIZE // 10)
            for k in list(_cache.keys())[:drop]:
                _cache.pop(k, None)
    _cache[key] = (value, now + timedelta(seconds=ttl_seconds))


def get_cache(key: str) -> Any | None:
    """Получить значение из кэша, если оно ещё не истекло."""
    entry = _cache.get(key)
    if entry:
        value, expires = entry
        if datetime.now(timezone.utc) < expires:
            return value
        del _cache[key]
    return None


def clear_cache(key: str | None = None) -> None:
    """Очистить весь кэш (и rate-limit) или конкретный ключ основного кэша."""
    if key:
        _cache.pop(key, None)
    else:
        _cache.clear()
        _rl_cache.clear()


def rate_limit_check_memory(
    key: str, max_per_minute: int, expire: int = 60
) -> tuple[bool, int]:
    """In-memory rate limiting — fallback, когда Redis недоступен.

    Префикс `rl:` уже содержится в ключе (см. utils/decorators.py),
    повторно его НЕ добавляем — иначе ключи в Redis и в памяти
    расходятся (был баг `rl:rl:`).

    Возвращает (allowed, current_count).

    Операция атомарна в asyncio (нет `await` между get и set),
    но не безопасна при многопроцессном запуске — для горизонтального
    масштабирования обязателен Redis.
    """
    now = datetime.now(timezone.utc)
    entry = _rl_cache.get(key)
    if entry:
        count, expires = entry
        if now < expires:
            count += 1
            _rl_cache[key] = (count, expires)
            return count <= max_per_minute, count
    if len(_rl_cache) >= _RL_MAX_SIZE:
        _rl_cleanup_expired(now)
        if len(_rl_cache) >= _RL_MAX_SIZE:
            drop = max(1, _RL_MAX_SIZE // 10)
            for k in list(_rl_cache.keys())[:drop]:
                _rl_cache.pop(k, None)
    _rl_cache[key] = (1, now + timedelta(seconds=expire))
    return 1 <= max_per_minute, 1


def clear_rate_limit_memory(key: str) -> None:
    """Сбросить счётчик rate limiting по ключу."""
    _rl_cache.pop(key, None)