import os
import sys
from logging.config import fileConfig
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool

# Добавляем корень проекта в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

# Загружаем переменные окружения
load_dotenv()

# Импортируем метаданные модели
from db.models import Base

# --- Конфигурация Alembic ---
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# --- Обработка DATABASE_URL ---
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL not set in environment")


def prepare_sync_db_url(url: str) -> tuple[str, dict]:
    """Преобразует DATABASE_URL для синхронного драйвера psycopg (v3).

    Возвращает (url, connect_args). SSL-параметры (sslmode/ssl) вынимаются
    из URL и передаются в connect_args — psycopg v3 понимает их как
    обычные kwargs connect(). Это работает и при sslmode=require.

    Если оставить sslmode в URL — psycopg v3 тоже справится, но при
    наличии спецсимволов в пароле URL-парсинг может испортить строку,
    поэтому безопаснее передавать ssl через kwargs.
    """
    parsed = urlparse(url)

    # asyncpg / голый postgresql → psycopg v3 (sync)
    if parsed.scheme in ("postgresql+asyncpg", "postgresql"):
        parsed = parsed._replace(scheme="postgresql+psycopg")

    query_params = parse_qs(parsed.query)

    connect_args: dict = {}
    sslmode: str | None = None

    for key in list(query_params.keys()):
        lower = key.lower()
        if lower == "sslmode":
            values = query_params.pop(key)
            if values:
                sslmode = values[0].lower()
        elif lower == "ssl":
            values = query_params.pop(key)
            if values:
                v = values[0].lower()
                mapping = {
                    "true": "require",
                    "false": "disable",
                    "allow": "allow",
                    "prefer": "prefer",
                    "require": "require",
                    "verify-ca": "verify-ca",
                    "verify-full": "verify-full",
                }
                sslmode = mapping.get(v)
        elif lower == "channel_binding":
            query_params.pop(key)

    if sslmode:
        connect_args["sslmode"] = sslmode

    new_query = urlencode(query_params, doseq=True)
    return urlunparse(parsed._replace(query=new_query)), connect_args


SYNC_DATABASE_URL, SYNC_CONNECT_ARGS = prepare_sync_db_url(DATABASE_URL)
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
        connect_args=SYNC_CONNECT_ARGS,
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