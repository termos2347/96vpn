import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import ClassVar

from config import settings

# Псевдонимы для модулей
MODULE_ALIASES = {
    "__main__": "MAIN",
    "asyncio": "ASYNCIO",
    "urllib3.connectionpool": "CONNECTION",
    "charset_normalizer": "CHARSET",
    "aiogram.event": "AIOGRAM",
    "aiohttp.access": "AIOHTTP",
    "aiohttp.internal": "AIOHTTP",
    "sqlalchemy.engine": "SQLALCHEMY",
    "alembic": "ALEMBIC",
    "handlers.common": "COMMON",
    "handlers.payment": "PAYMENT",
    "handlers.ui": "UI",
    "admin.bot": "ADMIN",
    "services.vpn_provider": "VPN_PROV",
    "services.vpn_manager": "VPN_MGR",
    "services.scheduler": "SCHED",
    "services.payment_yookassa": "YOOKASSA",
    "services.redis_service": "REDIS",
    "db.base": "DATABASE",
    "db.crud": "CRUD",
    "db.models": "MODELS",
    "internal_api": "API",
    "utils.logger": "LOGGER",
    "utils.decorators": "DECOR",
    "utils.validators": "VALID",
    "utils.encryption": "CRYPTO",
    "utils.cache": "CACHE",
}

LOG_FORMAT = "%(asctime)s | %(level_short)s | %(module_name)s: %(message)s"
LOG_DATE_FORMAT = "%Y.%m.%d %H:%M:%S"


def get_module_name(name: str) -> str:
    alias = MODULE_ALIASES.get(name)
    if alias:
        return alias
    parts = name.split(".")
    return parts[-1] if parts else name


class CompactFormatter(logging.Formatter):
    """Базовый форматтер для файла (без цветов)."""

    LEVEL_MAP: ClassVar[dict] = {
        "DEBUG": "D",
        "INFO": "I",
        "WARNING": "W",
        "ERROR": "E",
        "CRITICAL": "C",
    }

    def __init__(self):
        super().__init__(fmt=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

    def format(self, record):
        record.level_short = self.LEVEL_MAP.get(record.levelname, record.levelname[0])
        record.module_name = get_module_name(record.name)
        return super().format(record)


class ColoredFormatter(CompactFormatter):
    """Цветной форматтер для консоли."""

    COLORS: ClassVar[dict] = {
        "DEBUG": "\033[94m",  # Синий
        "INFO": "\033[92m",  # Зелёный
        "WARNING": "\033[93m",  # Жёлтый
        "ERROR": "\033[91m",  # Красный
        "CRITICAL": "\033[95m",  # Пурпурный
    }
    BOLD = "\033[1m"
    RESET = "\033[0m"

    def format(self, record):
        levelname = record.levelname
        letter = self.LEVEL_MAP.get(levelname, levelname[0])
        color = self.COLORS.get(levelname, "")
        colored_letter = f"{self.BOLD}{color}{letter}{self.RESET}"
        record.level_short = colored_letter
        record.module_name = get_module_name(record.name)
        return logging.Formatter.format(self, record)


def setup_logger():
    """Настраивает логирование с ротацией: консоль – цветная, файл – без цветов."""
    # Создаём свой логгер вместо использования корневого
    logger = logging.getLogger(__name__)

    # Консоль
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG if settings.DEBUG else logging.WARNING)
    console.setFormatter(ColoredFormatter())

    # Файл
    log_file = Path("logs/bot.log")
    log_file.parent.mkdir(exist_ok=True)
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=settings.LOG_MAX_BYTES,
        backupCount=settings.LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(CompactFormatter())

    # Корневой логгер – используем для глобальной настройки
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    for h in root.handlers[:]:
        root.removeHandler(h)
    root.addHandler(console)
    root.addHandler(file_handler)

    # Логируем через свой логгер, а не через корневой
    logger.info(
        "Логирование настроено: консоль (%s), файл (INFO)",
        "DEBUG" if settings.DEBUG else "WARNING+",
    )