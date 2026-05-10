import os
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

    # ---------- Telegram Bot ----------
    BOT_TOKEN: str

    # ---------- Proxy (опционально) ----------
    PROXY_URL: Optional[str] = None
    
    # Webhook (Telegram)
    WEBHOOK_URL: str = ""
    WEBHOOK_SECRET: str = ""
    ADMIN_WEBHOOK_URL: str = ""
    ADMIN_WEBHOOK_SECRET: str = ""
    
    # ---------- XUI панель (3x-ui) ----------
    XUI_BASE_URL: Optional[str] = None
    XUI_USERNAME: Optional[str] = None
    XUI_PASSWORD: Optional[str] = None
    XUI_INBOUND_ID: Optional[int] = None
    XUI_SUB_PORT: Optional[int] = None

    # ---------- FastAPI / Web ----------
    APP_NAME: str = "NeuroPrompt Premium"
    DEBUG: bool = False
        
    # ---------- SMTP ----------
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""

    # ---------- Database ----------
    DATABASE_URL: str

    # ---------- JWT ----------
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # ---------- Yookassa ----------
    YOOKASSA_SHOP_ID: str
    YOOKASSA_API_KEY: str
    YOOKASSA_RETURN_URL: str = "http://localhost:8000/dashboard"
    YOOKASSA_API_URL: str = "https://api.yookassa.ru/v3/"

    # ---------- Application ----------
    SITE_URL: str
    ADMIN_EMAIL: str

    # ---------- Subscription (веб-подписки AI) ----------
    MONTHLY_PRICE: float = 200.0
    QUARTERLY_PRICE: float = 500.0
    SEMIANNUAL_PRICE: float = 900.0
    SUBSCRIPTION_DAYS: int = 30
    PAYMENT_LINK_TTL_MINUTES: int = 120

    # ---------- VPN цены ----------
    VPN_PRICE_RUB_1M: float = 200.0
    VPN_PRICE_RUB_3M: float = 500.0
    VPN_PRICE_RUB_6M: float = 900.0
    VPN_PRICE_STARS_1M: float = 150.0
    VPN_PRICE_STARS_3M: float = 400.0
    VPN_PRICE_STARS_6M: float = 700.0
    VPN_PRICE_USDT_1M: float = 3.5
    VPN_PRICE_USDT_3M: float = 9.0
    VPN_PRICE_USDT_6M: float = 16.0

    # ---------- Обход DPI цены ----------
    BYPASS_PRICE_RUB_1M: float = 150.0
    BYPASS_PRICE_RUB_3M: float = 400.0
    BYPASS_PRICE_STARS_1M: float = 75.0
    BYPASS_PRICE_STARS_3M: float = 200.0
    BYPASS_PRICE_USDT_1M: float = 2.0
    BYPASS_PRICE_USDT_3M: float = 4.5

    # ---------- Admin ----------
    ADMIN_BOT_TOKEN: str = ""
    ADMIN_CHAT_ID: str = ""

    # ---------- Внутренний API (бот ↔ сайт) ----------
    INTERNAL_API_SECRET: str

    # Свойства для компактного доступа
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

# ---------- Экспорт переменных уровня модуля для бота ----------
TOKEN = settings.BOT_TOKEN
DATABASE_URL = settings.DATABASE_URL
PROXY_URL = settings.PROXY_URL
WEBHOOK_URL = settings.WEBHOOK_URL
WEBHOOK_SECRET = settings.WEBHOOK_SECRET

XUI_BASE_URL = settings.XUI_BASE_URL
XUI_USERNAME = settings.XUI_USERNAME
XUI_PASSWORD = settings.XUI_PASSWORD
XUI_INBOUND_ID = settings.XUI_INBOUND_ID
XUI_SUB_PORT = settings.XUI_SUB_PORT

VPN_PRICES = settings.VPN_PRICES
BYPASS_PRICES = settings.BYPASS_PRICES

# Внутренний API
INTERNAL_API_SECRET = settings.INTERNAL_API_SECRET
SITE_URL = settings.SITE_URL

# Админ-бот
ADMIN_BOT_TOKEN = settings.ADMIN_BOT_TOKEN
ADMIN_CHAT_ID = settings.ADMIN_CHAT_ID

PAYMENT_LINK_TTL_MINUTES = settings.PAYMENT_LINK_TTL_MINUTES