from pydantic_settings import BaseSettings
from typing import Optional

class WebSettings(BaseSettings):
    # FastAPI
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
    
    # Приложение
    SITE_URL: str = "http://localhost:8000"
    ADMIN_EMAIL: str
    
    # Подписка
    MONTHLY_PRICE: float = 290.0
    QUARTERLY_PRICE: float = 790.0
    SUBSCRIPTION_DAYS: int = 30
    
    class Config:
        env_file = ".env"
        case_sensitive = True

settings = WebSettings()
