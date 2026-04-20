from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
import os
import sys
from dotenv import load_dotenv

# Добавляем корень проекта в sys.path
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

# Загружаем .env
load_dotenv()

# Импортируем Base и модели
from db.models import Base
from config import DATABASE_URL

# this is the Alembic Config object
config = context.config

# Переопределяем sqlalchemy.url из переменной окружения
config.set_main_option("sqlalchemy.url", DATABASE_URL)

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here for 'autogenerate' support
target_metadata = Base.metadata