import json
import logging
import sys
import zoneinfo
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from cryptography.fernet import Fernet
from dotenv import load_dotenv
from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()

logger = logging.getLogger(__name__)


def clean_db_url(url: str) -> str:
    """Готовит DATABASE_URL к использованию с asyncpg.

    asyncpg не понимает `sslmode`/`ssl` как строковые параметры в URL —
    их наличие приводит к ошибке `connect() got an unexpected keyword
    argument 'sslmode'`. Поэтому полностью убираем SSL-параметры из URL.
    Для строгого SSL задавайте его через connect_args в db/base.py
    (см. get_asyncpg_ssl).
    """
    parsed = urlparse(url)
    query_params = parse_qs(parsed.query)

    for key in list(query_params.keys()):
        if key.lower() in ("sslmode", "ssl", "channel_binding"):
            query_params.pop(key)

    new_query = urlencode(query_params, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def get_asyncpg_ssl(url: str):
    """Возвращает SSL-конфигурацию для asyncpg.connect():

    None         — использовать asyncpg-дефолт ("prefer").
    False        — SSL отключён (sslmode=disable).
    SSLContext   — явная проверка (require/verify-ca/verify-full).
    """
    import ssl as ssl_module

    parsed = urlparse(url)
    query_params = parse_qs(parsed.query)

    sslmode: str | None = None
    for key in query_params:
        if key.lower() == "sslmode":
            values = query_params[key]
            if values:
                sslmode = values[0].lower()
            break

    if sslmode is None:
        return None
    if sslmode == "disable":
        return False

    ctx = ssl_module.create_default_context()
    if sslmode in ("require", "allow", "prefer"):
        ctx.check_hostname = False
        ctx.verify_mode = ssl_module.CERT_NONE
    elif sslmode == "verify-ca":
        ctx.check_hostname = False
        ctx.verify_mode = ssl_module.CERT_REQUIRED
    elif sslmode == "verify-full":
        pass
    else:
        return None
    return ctx


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", case_sensitive=True, extra="ignore"
    )

    # ---------- Режимы ----------
    DEBUG: bool = False
    SKIP_MIGRATION_CHECK: bool = False

    # ---------- Telegram ----------
    BOT_TOKEN: str = Field(..., min_length=1)
    ADMIN_BOT_TOKEN: str = Field(..., min_length=1)
    ADMIN_CHAT_ID: str = Field(..., min_length=1)

    # ---------- База данных ----------
    DATABASE_URL: str = Field(..., min_length=1)

    # ---------- Webhook ----------
    WEBHOOK_URL: str = Field(..., min_length=1)
    WEBHOOK_SECRET: str = Field(..., min_length=16)
    ADMIN_WEBHOOK_URL: str = Field(..., min_length=1)
    ADMIN_WEBHOOK_SECRET: str = Field(..., min_length=16)

    # ---------- Безопасность ----------
    ENCRYPTION_KEY: str = Field(..., min_length=1)
    INTERNAL_API_SECRET: str = Field(..., min_length=1)
    VERIFY_SSL: bool = True

    # ---------- Yookassa ----------
    YOOKASSA_SHOP_ID: str = Field(..., min_length=1)
    YOOKASSA_API_KEY: str = Field(..., min_length=1)
    YOOKASSA_RETURN_URL: str = "https://t.me/VPN_96_bot"
    YOOKASSA_API_URL: str = "https://api.yookassa.ru/v3/"
    YOOKASSA_TRUSTED_IPS: list[str] = Field(..., min_length=1)

    # ---------- Прокси, от которых принимаем X-Real-IP ----------
    TRUSTED_PROXY_IPS: list[str] = Field(
        default_factory=lambda: ["127.0.0.1", "::1"]
    )

    # ---------- 3x-UI Master Panel ----------
    XUI_MASTER_URL: str = Field(..., min_length=1)
    XUI_API_TOKEN: str = Field(..., min_length=1)
    XUI_INBOUND_ID: int = Field(..., ge=1)
    XUI_SUB_PORT: int = Field(..., ge=1, le=65535)

    # ---------- Rate limiting ----------
    RATE_LIMIT_START: int = 5
    RATE_LIMIT_HELP: int = 3
    RATE_LIMIT_MY_KEYS: int = 3
    RATE_LIMIT_BUY_VPN: int = 3
    RATE_LIMIT_TARIFF: int = 5
    RATE_LIMIT_PAYMENT: int = 3
    RATE_LIMIT_ADMIN: int = 10
    RATE_LIMIT_DEFAULT: int = 5

    # ---------- Redis ----------
    REDIS_ENABLED: bool = True
    REDIS_URL: str | None = None
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str = ""
    REDIS_CACHE_TTL: int = 60

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

    INTERNAL_API_HOST: str = "127.0.0.1"
    INTERNAL_API_PORT: int = 5001
    INTERNAL_API_URL: str = "http://localhost:5001"

    # ---------- Валидаторы ----------
    @field_validator(
        "YOOKASSA_TRUSTED_IPS", "TRUSTED_PROXY_IPS", mode="before"
    )
    @classmethod
    def parse_ip_list(cls, v):
        """Общий валидатор: строка JSON-массива или готовый list[str]."""
        if isinstance(v, list):
            if not v:
                raise ValueError("IP list must be a non-empty list")
            if not all(isinstance(item, str) for item in v):
                raise ValueError("IP list must contain only strings")
            return v
        elif isinstance(v, str):
            try:
                parsed = json.loads(v)
                if (
                    isinstance(parsed, list)
                    and parsed
                    and all(isinstance(item, str) for item in parsed)
                ):
                    return parsed
            except json.JSONDecodeError:
                pass
        raise ValueError("IP list must be a JSON array of IP/CIDR strings")

    @field_validator("DATABASE_URL")
    @classmethod
    def validate_database_url(cls, v):
        if not v.startswith("postgresql"):
            raise ValueError("DATABASE_URL must be a PostgreSQL connection string")
        return v

    @field_validator("ENCRYPTION_KEY")
    @classmethod
    def validate_encryption_key(cls, v):
        try:
            Fernet(v.encode())
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid ENCRYPTION_KEY: {e}")
        return v

    @field_validator("TIMEZONE")
    @classmethod
    def validate_timezone(cls, v):
        try:
            zoneinfo.ZoneInfo(v)
        except (ValueError, zoneinfo.ZoneInfoNotFoundError) as e:
            raise ValueError(f"Invalid TIMEZONE: {e}")
        return v

    @field_validator("YOOKASSA_SHOP_ID")
    @classmethod
    def validate_shop_id(cls, v):
        if not v.isdigit():
            raise ValueError("YOOKASSA_SHOP_ID must be numeric")
        return v

    @field_validator("YOOKASSA_API_KEY")
    @classmethod
    def validate_api_key(cls, v):
        if len(v) < 20:
            raise ValueError("YOOKASSA_API_KEY too short")
        return v

    @field_validator("WEBHOOK_URL", "ADMIN_WEBHOOK_URL")
    @classmethod
    def validate_webhook_url(cls, v: str, info) -> str:
        debug = info.data.get("DEBUG", False)
        if not debug:
            if not v.startswith("https://"):
                raise ValueError(f"{info.field_name} must use HTTPS in production")
        else:
            if v.startswith("http://"):
                allowed_local = ("http://localhost", "http://127.0.0.1")
                if not any(v.startswith(prefix) for prefix in allowed_local):
                    raise ValueError(
                        "In DEBUG mode, HTTP webhook URL must be "
                        "localhost or 127.0.0.1"
                    )
        return v

    @field_validator("XUI_MASTER_URL")
    @classmethod
    def validate_xui_url(cls, v):
        if not v.startswith(("http://", "https://")):
            raise ValueError("XUI_MASTER_URL must start with http:// or https://")
        return v

    @property
    def VPN_PRICES(self) -> dict:
        return {
            "rub": {
                "1m": self.VPN_PRICE_RUB_1M,
                "3m": self.VPN_PRICE_RUB_3M,
                "6m": self.VPN_PRICE_RUB_6M,
            },
        }

    @property
    def PERIOD_DAYS(self) -> dict:
        return {
            "1m": self.PERIOD_DAYS_1M,
            "3m": self.PERIOD_DAYS_3M,
            "6m": self.PERIOD_DAYS_6M,
        }


try:
    settings = Settings()  # type: ignore[call-arg]
except ValidationError as e:
    logging.basicConfig(level=logging.ERROR)
    logger.error("Configuration validation failed:")
    for error in e.errors():
        logger.error(f"  - {error.get('loc')[0]}: {error.get('msg')}")
    sys.exit(1)

TOKEN = settings.BOT_TOKEN
ADMIN_BOT_TOKEN = settings.ADMIN_BOT_TOKEN
ADMIN_CHAT_ID = settings.ADMIN_CHAT_ID
VPN_PRICES = settings.VPN_PRICES
INTERNAL_API_SECRET = settings.INTERNAL_API_SECRET
INTERNAL_API_HOST = settings.INTERNAL_API_HOST
INTERNAL_API_PORT = settings.INTERNAL_API_PORT
INTERNAL_API_URL = settings.INTERNAL_API_URL

DATABASE_URL = clean_db_url(settings.DATABASE_URL)

IPS_FILE = Path(__file__).resolve().parent / "yookassa_ip.json"


def load_trusted_ips() -> list[str] | None:
    if not IPS_FILE.exists():
        return None
    try:
        with open(IPS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list) and all(isinstance(x, str) for x in data):
            return data
        logger.warning(
            "yookassa_ip.json has invalid format, expected list of strings"
        )
        return None
    except (json.JSONDecodeError, OSError, TypeError) as e:
        logger.error(f"Failed to load yookassa_ip.json: {e}")
        return None


def save_trusted_ips(ips: list[str]) -> bool:
    try:
        with open(IPS_FILE, "w", encoding="utf-8") as f:
            json.dump(ips, f, indent=2, ensure_ascii=False)
        return True
    except (OSError, TypeError) as e:
        logger.error(f"Failed to save yookassa_ip.json: {e}")
        return False


_loaded_ips = load_trusted_ips()
if _loaded_ips is not None:
    if _loaded_ips:
        settings.YOOKASSA_TRUSTED_IPS = _loaded_ips
        logger.info(
            f"✅ YOOKASSA_TRUSTED_IPS overridden from yookassa_ip.json "
            f"({len(_loaded_ips)} entries)"
        )
    else:
        logger.warning(
            "⚠️ yookassa_ip.json contains an empty list. "
            "Keeping value from .env."
        )
else:
    logger.info(
        "ℹ️ Using YOOKASSA_TRUSTED_IPS from .env "
        "(yookassa_ip.json not found or invalid)"
    )