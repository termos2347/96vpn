import os
import sys
import logging
import zoneinfo
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv
from cryptography.fernet import Fernet

load_dotenv()

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore"
    )
    
    DEBUG: bool = False
    RUN_MIGRATIONS: bool = False

    # ---------- Telegram Bot ----------
    BOT_TOKEN: str
    ADMIN_BOT_TOKEN: str
    ADMIN_CHAT_ID: str

    # ---------- Proxy (опционально) ----------
    PROXY_URL: Optional[str] = None

    # ---------- Database ----------
    DATABASE_URL: str

    # ---------- Yookassa ----------
    YOOKASSA_SHOP_ID: str
    YOOKASSA_API_KEY: str
    YOOKASSA_RETURN_URL: str = "https://t.me/VPN_96_bot"
    YOOKASSA_API_URL: str = "https://api.yookassa.ru/v3/"
    
    # Webhook (Telegram)
    WEBHOOK_URL: str = ""
    WEBHOOK_SECRET: str = ""
    ADMIN_WEBHOOK_URL: str = ""
    ADMIN_WEBHOOK_SECRET: str = ""

    # ---------- Application ----------
    ENCRYPTION_KEY: str

    # ---------- Support ----------
    SUPPORT_USERNAME: str = "support_username"

    # ---------- LOG ----------
    LOG_LEVEL: str = "INFO"
    LOG_MAX_BYTES: int = 10 * 1024 * 1024
    LOG_BACKUP_COUNT: int = 5
    LOG_ACCESS_LEVEL: str = "WARNING"

    # ---------- Часовой пояс ----------
    TIMEZONE: str = "UTC"

    # ---------- Цены ----------
    VPN_PRICE_RUB_1M: float = 199.0
    VPN_PRICE_RUB_3M: float = 499.0
    VPN_PRICE_RUB_6M: float = 899.0
    VPN_PRICE_STARS_1M: float = 150.0
    VPN_PRICE_STARS_3M: float = 400.0
    VPN_PRICE_STARS_6M: float = 700.0
    VPN_PRICE_USDT_1M: float = 3.5
    VPN_PRICE_USDT_3M: float = 9.0
    VPN_PRICE_USDT_6M: float = 16.0

    # ---------- Обход DPI цены (оставляем на будущее) ----------
    BYPASS_PRICE_RUB_1M: float = 150.0
    BYPASS_PRICE_RUB_3M: float = 400.0
    BYPASS_PRICE_STARS_1M: float = 75.0
    BYPASS_PRICE_STARS_3M: float = 200.0
    BYPASS_PRICE_USDT_1M: float = 2.0
    BYPASS_PRICE_USDT_3M: float = 4.5

    # ---------- Внутренний API (бот ↔ сайт) ----------
    INTERNAL_API_SECRET: str
    INTERNAL_API_HOST: str = "0.0.0.0"
    INTERNAL_API_PORT: int = 5001
    INTERNAL_API_URL: str = "http://localhost:5001"

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

settings = Settings()

# ==================== ВАЛИДАЦИЯ ENCRYPTION_KEY ====================
def validate_encryption_key(key: str) -> None:
    if not key:
        raise ValueError(
            "❌ ENCRYPTION_KEY is not set in .env file.\n"
            "Generate a new key with:\n"
            "    python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"\n"
            "Then add it to your .env file."
        )
    try:
        Fernet(key.encode())
    except Exception as e:
        raise ValueError(
            f"❌ ENCRYPTION_KEY is invalid: {e}\n"
            f"Please generate a valid Fernet key as shown above.\n"
            f"Current key (first 10 chars): {key[:10]}..."
        )

validate_encryption_key(settings.ENCRYPTION_KEY)

# ==================== ВАЛИДАЦИЯ TIMEZONE ====================
try:
    zoneinfo.ZoneInfo(settings.TIMEZONE)
except Exception as e:
    raise ValueError(
        f"❌ Invalid TIMEZONE '{settings.TIMEZONE}': {e}\n"
        "Use valid IANA timezone name (e.g., Europe/Moscow, UTC, America/New_York)."
    )


# ==================== ВАЛИДАЦИЯ Yookassa ====================
if settings.YOOKASSA_SHOP_ID or settings.YOOKASSA_API_KEY:
    if not settings.YOOKASSA_SHOP_ID:
        raise ValueError("YOOKASSA_SHOP_ID is required when YOOKASSA_API_KEY is set")
    if not settings.YOOKASSA_API_KEY:
        raise ValueError("YOOKASSA_API_KEY is required when YOOKASSA_SHOP_ID is set")
    if not settings.YOOKASSA_SHOP_ID.isdigit():
        raise ValueError("YOOKASSA_SHOP_ID must be numeric")
    if len(settings.YOOKASSA_API_KEY) < 20:
        raise ValueError("YOOKASSA_API_KEY too short, seems invalid")
else:
    logging.warning("Yookassa credentials not set. RUB payments will not work.")

# ==================== ЭКСПОРТ ПЕРЕМЕННЫХ ДЛЯ БОТА ====================
TOKEN = settings.BOT_TOKEN
DATABASE_URL = settings.DATABASE_URL
PROXY_URL = settings.PROXY_URL
ADMIN_BOT_TOKEN = settings.ADMIN_BOT_TOKEN
ADMIN_CHAT_ID = settings.ADMIN_CHAT_ID

VPN_PRICES = settings.VPN_PRICES
BYPASS_PRICES = settings.BYPASS_PRICES

INTERNAL_API_SECRET = settings.INTERNAL_API_SECRET
INTERNAL_API_HOST = settings.INTERNAL_API_HOST
INTERNAL_API_PORT = settings.INTERNAL_API_PORT
INTERNAL_API_URL = settings.INTERNAL_API_URL