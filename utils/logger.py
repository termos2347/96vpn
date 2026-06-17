import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler
from config import settings

class ConsoleFilter(logging.Filter):
    """Фильтр, пропускающий только логи от наших модулей, если DEBUG=True."""
    def __init__(self, debug: bool):
        self.debug = debug
        # Список имён наших модулей
        self.allowed_prefixes = (
            '__main__',
            'handlers',
            'services',
            'db',
            'admin',
            'internal_api',
            'utils',
        )

    def filter(self, record):
        # Если DEBUG включён, пропускаем всё (уровень уже проверен обработчиком)
        if self.debug:
            return True
        # Если DEBUG выключен, пропускаем только WARNING и выше от наших модулей
        # Это даст ошибки и предупреждения в консоль
        if record.levelno >= logging.WARNING:
            # Проверяем, принадлежит ли логгер нашим модулям
            return any(record.name.startswith(prefix) for prefix in self.allowed_prefixes)
        return False

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
    # Если DEBUG=True, уровень DEBUG, иначе WARNING (чтобы видеть только ошибки и предупреждения)
    console.setLevel(logging.DEBUG if settings.DEBUG else logging.WARNING)
    console.setFormatter(formatter)
    # Добавляем фильтр, который учитывает DEBUG
    console.addFilter(ConsoleFilter(settings.DEBUG))

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
    root.setLevel(logging.DEBUG)  # чтобы все логи доходили до обработчиков
    for h in root.handlers[:]:
        root.removeHandler(h)
    root.addHandler(console)
    root.addHandler(file_handler)

    logging.info("Логирование настроено: консоль (%s), файл (%s)", 
                 "DEBUG" if settings.DEBUG else "WARNING+", "INFO")