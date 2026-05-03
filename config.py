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
    BOT_TOKEN: str  # обязательное
    
    # ---------- Admin ----------
    ADMIN_BOT_TOKEN: str = ""
    ADMIN_CHAT_ID: str = ""

    # ---------- Proxy (опционально) ----------
    PROXY_URL: Optional[str] = None

    # ---------- XUI панель (3x-ui) ----------
    XUI_BASE_URL: Optional[str] = None
    XUI_USERNAME: Optional[str] = None
    XUI_PASSWORD: Optional[str] = None
    XUI_INBOUND_ID: Optional[int] = None
    XUI_SUB_PORT: Optional[int] = None

    # ---------- FastAPI / Web ----------
    APP_NAME: str = "NeuroPrompt Premium"
    DEBUG: bool = False

    # ---------- Database ----------
    DATABASE_URL: str  # обязательное

    # ---------- JWT ----------
    SECRET_KEY: str  # обязательное
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # ---------- Yookassa ----------
    YOOKASSA_SHOP_ID: str  # обязательное
    YOOKASSA_API_KEY: str  # обязательное
    YOOKASSA_RETURN_URL: str = "http://localhost:8000/dashboard"
    YOOKASSA_API_URL: str = "https://api.yookassa.ru/v3/"  # для тестов: https://api.yookassa.ru/v3/sandbox/

    # ---------- Application ----------
    SITE_URL: str  # обязательное (например https://yourdomain.com)
    ADMIN_EMAIL: str  # обязательное

    # ---------- Subscription (веб-подписки AI) ----------
    MONTHLY_PRICE: float = 290.0
    QUARTERLY_PRICE: float = 790.0
    SUBSCRIPTION_DAYS: int = 30

    # ---------- Внутренний API (бот ↔ сайт) ----------
    INTERNAL_API_SECRET: str  # обязательное


# Создаём глобальный объект настроек
settings = Settings()

# Проверка XUI переменных (либо все, либо ничего)
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

XUI_BASE_URL = settings.XUI_BASE_URL
XUI_USERNAME = settings.XUI_USERNAME
XUI_PASSWORD = settings.XUI_PASSWORD
XUI_INBOUND_ID = settings.XUI_INBOUND_ID
XUI_SUB_PORT = settings.XUI_SUB_PORT

# Цены на подписки
VPN_PRICES = {
    "rub": {"1m": 300, "3m": 800, "6m": 1400},
    "stars": {"1m": 150, "3m": 400, "6m": 700},
    "usdt": {"1m": 3.5, "3m": 9.0, "6m": 16.0},
}
BYPASS_PRICES = {
    "rub": {"1m": 150, "3m": 400},
    "stars": {"1m": 75, "3m": 200},
    "usdt": {"1m": 2.0, "3m": 4.5},
}

# Внутренний API
INTERNAL_API_SECRET = settings.INTERNAL_API_SECRET
SITE_URL = settings.SITE_URL
ADMIN_BOT_TOKEN = settings.ADMIN_BOT_TOKEN
ADMIN_CHAT_ID = settings.ADMIN_CHAT_ID