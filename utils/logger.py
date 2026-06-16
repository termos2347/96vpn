import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler
from config import settings

class ConsoleFilter(logging.Filter):
    """Фильтр, пропускающий только логи от наших модулей."""
    def filter(self, record):
        # Список имён наших модулей (могут быть вложенные, поэтому проверяем начало)
        allowed_prefixes = (
            '__main__',
            'handlers',
            'services',
            'db',
            'admin',
            'internal_api',
            'utils',
        )
        return any(record.name.startswith(prefix) for prefix in allowed_prefixes)

def setup_logger():
    """Настраивает логирование с ротацией и разделением на консоль и файл."""
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    access_level = getattr(logging, settings.LOG_ACCESS_LEVEL.upper(), logging.WARNING)

    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # --- Консольный обработчик ---
    console = logging.StreamHandler(sys.stdout)
    # Уровень консоли: DEBUG если включён DEBUG, иначе INFO
    console.setLevel(logging.DEBUG if settings.DEBUG else logging.INFO)
    console.setFormatter(formatter)
    # Добавляем фильтр, чтобы в консоль не попадали логи библиотек
    console.addFilter(ConsoleFilter())

    # --- Файловый обработчик с ротацией ---
    log_file = Path("logs/bot.log")
    log_file.parent.mkdir(exist_ok=True)

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=settings.LOG_MAX_BYTES,
        backupCount=settings.LOG_BACKUP_COUNT,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)  # всегда пишем INFO и выше
    file_handler.setFormatter(formatter)

    # --- Настройка корневого логгера ---
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)  # чтобы все логи (включая DEBUG) доходили до обработчиков
    # Удаляем старые обработчики, если были
    for h in root.handlers[:]:
        root.removeHandler(h)
    root.addHandler(console)
    root.addHandler(file_handler)

    logging.info("Логирование настроено: консоль (%s), файл (%s)", 
                 "DEBUG" if settings.DEBUG else "INFO", "INFO")