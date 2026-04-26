import logging
import sys
from pathlib import Path

def setup_logger():
    """Настраивает логирование с ротацией и структурированным выводом."""
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Убираем существующие хендлеры
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # Форматтер
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Консольный хендлер
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Файловый хендлер с ротацией
    log_file = Path("logs/bot.log")
    log_file.parent.mkdir(exist_ok=True)

    from logging.handlers import RotatingFileHandler
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger