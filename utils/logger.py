import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler
from config import settings

def setup_logger():
    """Настраивает логирование с ротацией и параметрами из .env."""
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    access_level = getattr(logging, settings.LOG_ACCESS_LEVEL.upper(), logging.WARNING)

    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Консольный вывод
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(log_level)
    console.setFormatter(formatter)

    # Файловый вывод с ротацией
    log_file = Path("logs/bot.log")
    log_file.parent.mkdir(exist_ok=True)

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=settings.LOG_MAX_BYTES,
        backupCount=settings.LOG_BACKUP_COUNT,
        encoding='utf-8'
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)

    # Корневой логгер
    root = logging.getLogger()
    root.setLevel(log_level)
    for h in root.handlers[:]:
        root.removeHandler(h)
    root.addHandler(console)
    root.addHandler(file_handler)

    # Логгеры Uvicorn и aiohttp
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error", "aiohttp.access", "aiohttp.server"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.addHandler(console)
        logger.addHandler(file_handler)
        logger.propagate = False
        if "access" in name:
            logger.setLevel(access_level)
        else:
            logger.setLevel(log_level)

    return root