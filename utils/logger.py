import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler
from config import settings

# Псевдонимы для понятных названий модулей
MODULE_ALIASES = {
    '__main__': 'MAIN',
    'asyncio': 'ASYNCIO',
    'urllib3.connectionpool': 'CONNECTION',
    'charset_normalizer': 'CHARSET',
    'aiogram.event': 'AIOGRAM',
    'aiohttp.access': 'AIOHTTP',
    'aiohttp.internal': 'AIOHTTP',
    'sqlalchemy.engine': 'SQLALCHEMY',
    'alembic': 'ALEMBIC',
    'handlers.common': 'COMMON',
    'handlers.payment': 'PAYMENT',
    'handlers.ui': 'UI',
    'admin.bot': 'ADMIN',
    'services.vpn_provider': 'VPN_PROV',
    'services.vpn_manager': 'VPN_MGR',
    'services.scheduler': 'SCHED',
    'services.payment_yookassa': 'YOOKASSA',
    'services.redis_service': 'REDIS',
    'db.base': 'DATABASE',
    'db.crud': 'CRUD',
    'db.models': 'MODELS',
    'internal_api': 'API',
    'utils.logger': 'LOGGER',
    'utils.decorators': 'DECOR',
    'utils.validators': 'VALID',
    'utils.encryption': 'CRYPTO',
    'utils.cache': 'CACHE',
}

def get_module_name(name: str) -> str:
    """Возвращает понятное имя модуля (из словаря или последняя часть)."""
    alias = MODULE_ALIASES.get(name)
    if alias:
        return alias
    parts = name.split('.')
    return parts[-1] if parts else name


class CompactFormatter(logging.Formatter):
    LEVEL_MAP = {
        'DEBUG': 'D',
        'INFO': 'I',
        'WARNING': 'W',
        'ERROR': 'E',
        'CRITICAL': 'C'
    }

    def format(self, record):
        record.level_short = self.LEVEL_MAP.get(record.levelname, record.levelname[0])
        record.module_name = get_module_name(record.name)
        return super().format(record)


def setup_logger():
    """Настраивает логирование с компактным форматом и осмысленными именами модулей."""
    formatter = CompactFormatter(
        '%(asctime)s | %(level_short)-1s | %(module_name)s: %(message)s',
        datefmt='%Y.%m.%d %H:%M:%S'
    )

    # Консоль
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG if settings.DEBUG else logging.WARNING)
    console.setFormatter(formatter)

    # Файл
    log_file = Path("logs/bot.log")
    log_file.parent.mkdir(exist_ok=True)
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=settings.LOG_MAX_BYTES,
        backupCount=settings.LOG_BACKUP_COUNT,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)

    # Корневой логгер
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    for h in root.handlers[:]:
        root.removeHandler(h)
    root.addHandler(console)
    root.addHandler(file_handler)

    logging.info("Логирование настроено: консоль (%s), файл (INFO)",
                 "DEBUG" if settings.DEBUG else "WARNING+")