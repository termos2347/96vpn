# config.py (новая версия)
import os
import sys
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore"
    )
    
    DEBUG: bool = False

    # ---------- Telegram Bot ----------
    BOT_TOKEN: str
    ADMIN_BOT_TOKEN: str
    ADMIN_CHAT_ID: str

    # ---------- Proxy (опционально) ----------
    PROXY_URL: Optional[str] = None

    # ---------- SENTRY ----------
    SENTRY_DSN: Optional[str] = None

    # ---------- XUI панель (3x-ui) ----------
    XUI_BASE_URL: Optional[str] = None
    XUI_USERNAME: Optional[str] = None
    XUI_PASSWORD: Optional[str] = None
    XUI_INBOUND_ID: Optional[int] = None
    XUI_SUB_PORT: Optional[int] = None

    # ---------- Database ----------
    DATABASE_URL: str

    # ---------- Yookassa ----------
    YOOKASSA_SHOP_ID: str
    YOOKASSA_API_KEY: str
    YOOKASSA_RETURN_URL: str = "https://t.me/your_bot"   # или пустая строка, не важно
    YOOKASSA_API_URL: str = "https://api.yookassa.ru/v3/"
    
    # Webhook (Telegram)
    WEBHOOK_URL: str = ""
    WEBHOOK_SECRET: str = ""
    ADMIN_WEBHOOK_URL: str = ""
    ADMIN_WEBHOOK_SECRET: str = ""
    DEBUG: bool = False

    # ---------- Application ----------
    ENCRYPTION_KEY: str

    # ---------- Support ----------
    SUPPORT_USERNAME: str = "support_username"

    # ---------- LOG ----------
    LOG_LEVEL: str = "INFO"
    LOG_MAX_BYTES: int = 10 * 1024 * 1024   # 10 MB
    LOG_BACKUP_COUNT: int = 5
    LOG_ACCESS_LEVEL: str = "WARNING"

    # ---------- VPN цены ----------
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
    INTERNAL_API_HOST: str = "localhost"
    INTERNAL_API_PORT: int = 8001
    INTERNAL_API_URL: str = "http://localhost:8001"

    # ---------- Subscription ----------
    SUBSCRIPTION_DAYS: int = 30
    PAYMENT_LINK_TTL_MINUTES: int = 120   # для обратной совместимости, можно оставить

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

# Валидация XUI переменных
xui_vars = [
    settings.XUI_BASE_URL,
    settings.XUI_USERNAME,
    settings.XUI_PASSWORD,
    settings.XUI_INBOUND_ID,
    settings.XUI_SUB_PORT,
]
xui_filled = sum(1 for v in xui_vars if v is not None and str(v).strip())
if 0 < xui_filled < len(xui_vars):
    raise ValueError("Все переменные XUI должны быть заполнены вместе или оставлены пустыми")

# Валидация Yookassa
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
    import logging
    logging.warning("Yookassa credentials not set. RUB payments will not work.")

# Экспорт переменных для бота
TOKEN = settings.BOT_TOKEN
DATABASE_URL = settings.DATABASE_URL
PROXY_URL = settings.PROXY_URL
ADMIN_BOT_TOKEN = settings.ADMIN_BOT_TOKEN
ADMIN_CHAT_ID = settings.ADMIN_CHAT_ID

XUI_BASE_URL = settings.XUI_BASE_URL
XUI_USERNAME = settings.XUI_USERNAME
XUI_PASSWORD = settings.XUI_PASSWORD
XUI_INBOUND_ID = settings.XUI_INBOUND_ID
XUI_SUB_PORT = settings.XUI_SUB_PORT

VPN_PRICES = settings.VPN_PRICES
BYPASS_PRICES = settings.BYPASS_PRICES

INTERNAL_API_SECRET = settings.INTERNAL_API_SECRET
INTERNAL_API_HOST = settings.INTERNAL_API_HOST
INTERNAL_API_PORT = settings.INTERNAL_API_PORT
INTERNAL_API_URL = settings.INTERNAL_API_URL

PAYMENT_LINK_TTL_MINUTES = settings.PAYMENT_LINK_TTL_MINUTES