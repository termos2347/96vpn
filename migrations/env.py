import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlunparse, urlencode

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.ext.asyncio import create_async_engine
from dotenv import load_dotenv

# Добавляем корень проекта в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

# Загружаем переменные окружения
load_dotenv()

# Импортируем метаданные модели
from db.base import Base
from config import settings

# --- Конфигурация Alembic ---
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# --- Обработка DATABASE_URL ---
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL not set in environment")

def clean_db_url_for_psycopg2(url: str) -> str:
    """
    Преобразует DATABASE_URL для синхронного драйвера psycopg2.
    Удаляет несовместимые параметры, такие как 'ssl', 'sslmode'.
    """
    parsed = urlparse(url)

    # Если это asyncpg URL, меняем схему на стандартную
    if parsed.scheme in ("postgresql+asyncpg", "postgresql+psycopg"):
        parsed = parsed._replace(scheme="postgresql")

    # Извлекаем параметры запроса
    query_params = parse_qs(parsed.query)
    # Удаляем 'ssl' и 'sslmode', если они есть
    query_params.pop('ssl', None)
    query_params.pop('sslmode', None)

    # Собираем URL заново
    new_query = urlencode(query_params, doseq=True)
    clean_url = urlunparse(parsed._replace(query=new_query))
    return clean_url

# Получаем очищенный URL для синхронного драйвера
SYNC_DATABASE_URL = clean_db_url_for_psycopg2(DATABASE_URL)
config.set_main_option("sqlalchemy.url", SYNC_DATABASE_URL)

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()