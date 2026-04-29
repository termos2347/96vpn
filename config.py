import os
from typing import Optional
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

# Загружаем .env, чтобы переменные были доступны
load_dotenv()

class Settings(BaseSettings):
    # Telegram Bot
    BOT_TOKEN: str
    
    # Proxy
    PROXY_URL: Optional[str] = None
    
    # XUI
    XUI_BASE_URL: Optional[str] = None
    XUI_USERNAME: Optional[str] = None
    XUI_PASSWORD: Optional[str] = None
    XUI_INBOUND_ID: Optional[int] = None
    XUI_SUB_PORT: Optional[int] = None

    # FastAPI / Web
    APP_NAME: str = "NeuroPrompt Premium"
    DEBUG: bool = False
    
    # Database
    DATABASE_URL: str = "sqlite:///./test.db"
    
    # JWT
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # Yookassa
    YOOKASSA_SHOP_ID: str
    YOOKASSA_API_KEY: str
    YOOKASSA_RETURN_URL: str = "http://localhost:8000/dashboard"
    
    # Application
    SITE_URL: str = "http://localhost:8000"
    ADMIN_EMAIL: str
    
    # Subscription
    MONTHLY_PRICE: float = 290.0
    QUARTERLY_PRICE: float = 790.0
    SUBSCRIPTION_DAYS: int = 30
    
    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"

settings = Settings()

# Для обратной совместимости с существующим кодом бота
TOKEN = settings.BOT_TOKEN
DATABASE_URL = settings.DATABASE_URL
PROXY_URL = settings.PROXY_URL

XUI_BASE_URL = settings.XUI_BASE_URL
XUI_USERNAME = settings.XUI_USERNAME
XUI_PASSWORD = settings.XUI_PASSWORD
XUI_INBOUND_ID = settings.XUI_INBOUND_ID
XUI_SUB_PORT = settings.XUI_SUB_PORT

# Проверяем, что все XUI переменные либо все заполнены, либо все пусты
xui_vars = [XUI_BASE_URL, XUI_USERNAME, XUI_PASSWORD, XUI_INBOUND_ID, XUI_SUB_PORT]
xui_filled_count = sum(1 for v in xui_vars if v is not None and str(v).strip())

if 0 < xui_filled_count < 5:
    raise ValueError("Все переменные XUI должны быть заполнены вместе или оставлены пустыми")

# ---------- Цены на подписки ----------
# VPN: ключ - валюта, значение - словарь {период: цена}
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
