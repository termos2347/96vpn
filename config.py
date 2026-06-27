import os
import sys
import logging
import zoneinfo
import json
from pathlib import Path
from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator, ValidationError
from dotenv import load_dotenv
from cryptography.fernet import Fernet

load_dotenv()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore"
    )

    # ---------- Режимы ----------
    DEBUG: bool = False

    # ---------- Telegram ----------
    BOT_TOKEN: str = Field(..., min_length=1)
    ADMIN_BOT_TOKEN: str = Field(..., min_length=1)
    ADMIN_CHAT_ID: str = Field(..., min_length=1)

    # ---------- База данных ----------
    DATABASE_URL: str = Field(..., min_length=1)

    # ---------- Webhook ----------
    WEBHOOK_URL: str = Field(..., min_length=1)
    WEBHOOK_SECRET: str = ""
    ADMIN_WEBHOOK_URL: str = Field(..., min_length=1)
    ADMIN_WEBHOOK_SECRET: str = ""

    # ---------- Безопасность ----------
    ENCRYPTION_KEY: str = Field(..., min_length=1)
    INTERNAL_API_SECRET: str = Field(..., min_length=1)
    VERIFY_SSL: bool = True

    # ---------- Yookassa ----------
    YOOKASSA_SHOP_ID: str = Field(..., min_length=1)
    YOOKASSA_API_KEY: str = Field(..., min_length=1)
    YOOKASSA_RETURN_URL: str = "https://t.me/VPN_96_bot"
    YOOKASSA_API_URL: str = "https://api.yookassa.ru/v3/"
    YOOKASSA_TRUSTED_IPS: List[str] = Field(..., min_length=1)

    # ---------- Остальное ----------
    SUPPORT_USERNAME: str = "support_username"
    LOG_LEVEL: str = "INFO"
    LOG_MAX_BYTES: int = 10 * 1024 * 1024
    LOG_BACKUP_COUNT: int = 5
    LOG_ACCESS_LEVEL: str = "WARNING"
    TIMEZONE: str = "UTC"
    MAX_BROADCAST_FILE_SIZE_MB: int = 20

    PERIOD_DAYS_1M: int = 30
    PERIOD_DAYS_3M: int = 90
    PERIOD_DAYS_6M: int = 180

    VPN_PRICE_RUB_1M: float = 199.0
    VPN_PRICE_RUB_3M: float = 499.0
    VPN_PRICE_RUB_6M: float = 899.0
    VPN_PRICE_STARS_1M: float = 150.0
    VPN_PRICE_STARS_3M: float = 400.0
    VPN_PRICE_STARS_6M: float = 700.0
    VPN_PRICE_USDT_1M: float = 3.5
    VPN_PRICE_USDT_3M: float = 9.0
    VPN_PRICE_USDT_6M: float = 16.0

    BYPASS_PRICE_RUB_1M: float = 150.0
    BYPASS_PRICE_RUB_3M: float = 400.0
    BYPASS_PRICE_STARS_1M: float = 75.0
    BYPASS_PRICE_STARS_3M: float = 200.0
    BYPASS_PRICE_USDT_1M: float = 2.0
    BYPASS_PRICE_USDT_3M: float = 4.5

    INTERNAL_API_HOST: str = "0.0.0.0"
    INTERNAL_API_PORT: int = 5001
    INTERNAL_API_URL: str = "http://localhost:5001"

    # ---------- Валидаторы ----------
    @field_validator('YOOKASSA_TRUSTED_IPS', mode='before')
    @classmethod
    def parse_trusted_ips(cls, v):
        if isinstance(v, list):
            if not v:
                raise ValueError("YOOKASSA_TRUSTED_IPS must be a non-empty list")
            if not all(isinstance(item, str) for item in v):
                raise ValueError("YOOKASSA_TRUSTED_IPS must contain only strings")
            return v
        elif isinstance(v, str):
            try:
                parsed = json.loads(v)
                if isinstance(parsed, list) and parsed and all(isinstance(item, str) for item in parsed):
                    return parsed
            except json.JSONDecodeError:
                pass
        raise ValueError("YOOKASSA_TRUSTED_IPS must be a JSON array of IP/CIDR strings")

    @field_validator('DATABASE_URL')
    @classmethod
    def validate_database_url(cls, v):
        if not v.startswith('postgresql'):
            raise ValueError("DATABASE_URL must be a PostgreSQL connection string")
        return v

    @field_validator('ENCRYPTION_KEY')
    @classmethod
    def validate_encryption_key(cls, v):
        try:
            Fernet(v.encode())
        except Exception as e:
            raise ValueError(f"Invalid ENCRYPTION_KEY: {e}")
        return v

    @field_validator('TIMEZONE')
    @classmethod
    def validate_timezone(cls, v):
        try:
            zoneinfo.ZoneInfo(v)
        except Exception as e:
            raise ValueError(f"Invalid TIMEZONE: {e}")
        return v

    @field_validator('YOOKASSA_SHOP_ID')
    @classmethod
    def validate_shop_id(cls, v):
        if not v.isdigit():
            raise ValueError("YOOKASSA_SHOP_ID must be numeric")
        return v

    @field_validator('YOOKASSA_API_KEY')
    @classmethod
    def validate_api_key(cls, v):
        if len(v) < 20:
            raise ValueError("YOOKASSA_API_KEY too short")
        return v

    # ---------- Свойства ----------
    @property
    def VPN_PRICES(self) -> dict:
        return {
            "rub": {"1m": self.VPN_PRICE_RUB_1M, "3m": self.VPN_PRICE_RUB_3M, "6m": self.VPN_PRICE_RUB_6M},
            "stars": {"1m": self.VPN_PRICE_STARS_1M, "3m": self.VPN_PRICE_STARS_3M, "6m": self.VPN_PRICE_STARS_6M},
            "usdt": {"1m": self.VPN_PRICE_USDT_1M, "3m": self.VPN_PRICE_USDT_3M, "6m": self.VPN_PRICE_USDT_6M},
        }

    @property
    def BYPASS_PRICES(self) -> dict:
        return {
            "rub": {"1m": self.BYPASS_PRICE_RUB_1M, "3m": self.BYPASS_PRICE_RUB_3M},
            "stars": {"1m": self.BYPASS_PRICE_STARS_1M, "3m": self.BYPASS_PRICE_STARS_3M},
            "usdt": {"1m": self.BYPASS_PRICE_USDT_1M, "3m": self.BYPASS_PRICE_USDT_3M},
        }

    @property
    def PERIOD_DAYS(self) -> dict:
        return {
            "1m": self.PERIOD_DAYS_1M,
            "3m": self.PERIOD_DAYS_3M,
            "6m": self.PERIOD_DAYS_6M,
        }


# ---------- Создание экземпляра с обработкой ошибок ----------
try:
    settings = Settings()
except ValidationError as e:
    logging.basicConfig(level=logging.ERROR)
    logging.error("Configuration validation failed:")
    for error in e.errors():
        logging.error(f"  - {error.get('loc')[0]}: {error.get('msg')}")
    sys.exit(1)

# ---------- Экспорт для обратной совместимости ----------
TOKEN = settings.BOT_TOKEN
DATABASE_URL = settings.DATABASE_URL
ADMIN_BOT_TOKEN = settings.ADMIN_BOT_TOKEN
ADMIN_CHAT_ID = settings.ADMIN_CHAT_ID
VPN_PRICES = settings.VPN_PRICES
BYPASS_PRICES = settings.BYPASS_PRICES
INTERNAL_API_SECRET = settings.INTERNAL_API_SECRET
INTERNAL_API_HOST = settings.INTERNAL_API_HOST
INTERNAL_API_PORT = settings.INTERNAL_API_PORT
INTERNAL_API_URL = settings.INTERNAL_API_URL


# ---------- НОВЫЙ БЛОК: работа с yookassa_ip.json ----------
IPS_FILE = Path("yookassa_ip.json")

def load_trusted_ips() -> Optional[List[str]]:
    """Загружает список доверенных IP из файла. Возвращает None при ошибке или отсутствии."""
    if not IPS_FILE.exists():
        return None
    try:
        with open(IPS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list) and all(isinstance(x, str) for x in data):
            return data
        else:
            logging.warning("yookassa_ip.json has invalid format, expected list of strings")
            return None
    except Exception as e:
        logging.error(f"Failed to load yookassa_ip.json: {e}")
        return None

def save_trusted_ips(ips: List[str]) -> bool:
    """Сохраняет список IP в файл. Возвращает True при успехе."""
    try:
        with open(IPS_FILE, "w", encoding="utf-8") as f:
            json.dump(ips, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logging.error(f"Failed to save yookassa_ip.json: {e}")
        return False

# Если файл не существует, создаём его с текущим списком из .env
if not IPS_FILE.exists():
    initial_ips = settings.YOOKASSA_TRUSTED_IPS
    if save_trusted_ips(initial_ips):
        logging.info(f"✅ Created yookassa_ip.json with initial IPs from .env ({len(initial_ips)} entries)")
    else:
        logging.warning("⚠️ Could not create yookassa_ip.json, will use .env value")

# Загружаем из файла (если он существует, даже только что создан)
_loaded_ips = load_trusted_ips()
if _loaded_ips is not None:
    if _loaded_ips:
        settings.YOOKASSA_TRUSTED_IPS = _loaded_ips
        logging.info(f"✅ YOOKASSA_TRUSTED_IPS overridden from yookassa_ip.json ({len(_loaded_ips)} entries)")
    else:
        logging.warning("⚠️ yookassa_ip.json contains an empty list. Keeping value from .env.")
        # Можно также создать файл заново с .env, чтобы исправить ситуацию:
        # save_trusted_ips(settings.YOOKASSA_TRUSTED_IPS)
else:
    logging.info("ℹ️ Using YOOKASSA_TRUSTED_IPS from .env (file not found or invalid)")
    