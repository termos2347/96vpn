import ipaddress
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
    INTERNAL_API_SECRET: str = Field(..., min_length=32)
    VERIFY_SSL: bool = True

    # ---------- Yookassa ----------
    YOOKASSA_SHOP_ID: str = Field(..., min_length=1)
    YOOKASSA_API_KEY: str = Field(..., min_length=1)
    YOOKASSA_RETURN_URL: str = "https://t.me/VPN_96_bot"
    YOOKASSA_API_URL: str = "https://api.yookassa.ru/v3/"
    YOOKASSA_TRUSTED_IPS: list[str] = Field(..., min_length=1)

    # ---------- Прокси, от которых принимаем X-Real-IP ----------
    # Дефолт — пустой список. Если перед ботом стоит nginx —
    # оператор должен явно добавить его IP/CIDR.
    TRUSTED_PROXY_IPS: list[str] = Field(default_factory=list)

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

    @property
    def INTERNAL_API_URL(self) -> str:
        """Computed-свойство: не может рассинхронизироваться с host+port."""
        return f"http://{self.INTERNAL_API_HOST}:{self.INTERNAL_API_PORT}"

    # ---------- Валидаторы ----------
    @field_validator(
        "YOOKASSA_TRUSTED_IPS", "TRUSTED_PROXY_IPS", mode="before"
    )
    @classmethod
    def parse_ip_list(cls, v):
        """Общий валидатор: строка JSON-массива или готовый list[str]."""
        if isinstance(v, list):
            if not all(isinstance(item, str) for item in v):
                raise ValueError("IP list must contain only strings")
            return v
        elif isinstance(v, str):
            try:
                parsed = json.loads(v)
                if isinstance(parsed, list) and all(
                    isinstance(item, str) for item in parsed
                ):
                    return parsed
            except json.JSONDecodeError:
                pass
        raise ValueError("IP list must be a JSON array of IP/CIDR strings")

    @field_validator("TRUSTED_PROXY_IPS")
    @classmethod
    def validate_proxy_ips(cls, v: list[str]) -> list[str]:
        """Проверяем, что каждый элемент — валидный IP/CIDR."""
        for item in v:
            try:
                ipaddress.ip_network(item, strict=False)
            except ValueError as e:
                raise ValueError(
                    f"Invalid IP/CIDR in TRUSTED_PROXY_IPS: {item!r} ({e})"
                )
        return v

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
    """Загружает yookassa_ip.json с валидацией каждого элемента."""
    if not IPS_FILE.exists():
        return None
    try:
        with open(IPS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            logger.warning(
                "yookassa_ip.json: expected JSON array, got %r",
                type(data).__name__,
            )
            return None
        validated: list[str] = []
        for item in data:
            if not isinstance(item, str):
                logger.warning(
                    f"yookassa_ip.json: skipping non-string item {item!r}"
                )
                continue
            try:
                ipaddress.ip_network(item, strict=False)
            except ValueError:
                logger.warning(
                    f"yookassa_ip.json: skipping invalid IP/CIDR {item!r}"
                )
                continue
            validated.append(item)
        return validated if validated else None
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


# BUGFIX: раньше здесь был set из строк и сравнение через `in`. Это не
# ловило `127.0.0.2`, `127.0.0.1/32` и т.п. — guardrail проскакивал
# небезопасную конфигурацию. Теперь используем ipaddress и проверяем,
# что CIDR целиком лежит в loopback-пространстве.
_LOOPBACK_NETWORKS: tuple[
    ipaddress.IPv4Network | ipaddress.IPv6Network, ...
] = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
)


def _is_loopback_network(cidr: str) -> bool:
    """True, если cidr целиком лежит в loopback-пространстве."""
    try:
        net = ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return False
    for lo in _LOOPBACK_NETWORKS:
        if net.version != lo.version:
            continue
        # Pylance не умеет связывать `net.version != lo.version`
        # с типами IPv4Network / IPv6Network (typeshed: subnet_of —
        # self-тип). Явный isinstance-narrowing делает проверку
        # типов корректной и одновременно гарантирует, что
        # subnet_of вызывается только на совпадающих версиях.
        if isinstance(net, ipaddress.IPv4Network) and isinstance(
            lo, ipaddress.IPv4Network
        ):
            if net.subnet_of(lo) or net == lo:
                return True
        elif isinstance(net, ipaddress.IPv6Network) and isinstance(
            lo, ipaddress.IPv6Network
        ):
            if net.subnet_of(lo) or net == lo:
                return True
    return False


def _check_proxy_safety() -> None:
    """Проверяет безопасность конфигурации прокси и IP-фильтра.

    SECURITY (fail-safe вместо fail-closed):
    Раньше бот кидал RuntimeError и не запускался, если в
    YOOKASSA_TRUSTED_IPS был loopback при пустом TRUSTED_PROXY_IPS и
    DEBUG=false. Это ломало СВЕЖУЮ установку из репозитория (в
    yookassa_ip.json лежит 127.0.0.1) — бот падал на импорте config.

    Теперь:
      * loopback-записи АВТОМАТИЧЕСКИ УДАЛЯЮТСЯ из
        YOOKASSA_TRUSTED_IPS (с громким предупреждением) — подделать
        вебхук через localhost нельзя;
      * если после фильтрации список опустел — бот не стартует
        (иначе все вебхуки YooKassa будут отклонены, что тоже
        неприемлемо, но уже молча);
      * в DEBUG-режиме loopback разрешён (localtunnel, локальные
        тесты) — фильтрация не применяется.
    """

    # BUGFIX: раньше проверка срабатывала только при INTERNAL_API_HOST
    # НЕ loopback — т.е. ПРОПУСКАЛА самый частый прод-сценарий:
    # "nginx на той же машине, бот слушает 127.0.0.1, TRUSTED_PROXY_IPS пуст".
    # В этом случае get_client_ip() возвращает 127.0.0.1, X-Real-IP
    # игнорируется, и ВСЕ вебхуки ЮKassa получают 403 (оплаты "висят").
    # Теперь предупреждаем в обоих случаях.
    if not settings.DEBUG and not settings.TRUSTED_PROXY_IPS:
        if settings.INTERNAL_API_HOST in ("127.0.0.1", "::1", "localhost"):
            logger.warning(
                "⚠️ INTERNAL_API_HOST=%r (loopback) + TRUSTED_PROXY_IPS "
                "пуст при DEBUG=false. Если снаружи стоит reverse proxy "
                "(nginx/caddy) — X-Real-IP приниматься НЕ будет, и ВСЕ "
                "вебхуки ЮKassa получат 403. Добавьте CIDR прокси в "
                "TRUSTED_PROXY_IPS (например, ['127.0.0.1/32']).",
                settings.INTERNAL_API_HOST,
            )
        else:
            logger.warning(
                "⚠️ INTERNAL_API_HOST=%r + TRUSTED_PROXY_IPS пуст. "
                "Бот принимает подключения напрямую. Если перед ним "
                "reverse proxy — добавьте его CIDR в TRUSTED_PROXY_IPS.",
                settings.INTERNAL_API_HOST,
            )

    loopback = [
        ip for ip in settings.YOOKASSA_TRUSTED_IPS if _is_loopback_network(ip)
    ]
    if not loopback:
        return

    if settings.DEBUG:
        # В DEBUG loopback допустим (localtunnel, локальные тесты).
        return

    filtered = [
        ip
        for ip in settings.YOOKASSA_TRUSTED_IPS
        if not _is_loopback_network(ip)
    ]

    if not settings.TRUSTED_PROXY_IPS:
        logger.error(
            "🚨 КРИТИЧНО: DEBUG=false, TRUSTED_PROXY_IPS пуст, а "
            "YOOKASSA_TRUSTED_IPS содержит loopback: %s. "
            "Loopback будет УДАЛЁН из доверенных IP — иначе любой клиент "
            "мог бы подделать вебхук YooKassa. "
            "Чтобы вернуть loopback: (1) задайте TRUSTED_PROXY_IPS (CIDR "
            "nginx); (2) или для localtunnel-отладки выставьте DEBUG=true.",
            loopback,
        )
    else:
        logger.warning(
            "⚠️ YOOKASSA_TRUSTED_IPS содержит loopback (%s) при DEBUG=false. "
            "Loopback будет удалён из доверенных IP (безопасность). "
            "Если loopback был нужен — используйте TRUSTED_PROXY_IPS + "
            "X-Real-IP вместо прямого loopback.",
            loopback,
        )

    if not filtered:
        # Все доверенные IP были loopback'ом. В проде это гарантированно
        # означает, что все вебхуки YooKassa будут отклонены. Не стартуем
        # и громко объясняем оператору, что делать.
        raise RuntimeError(
            f"YOOKASSA_TRUSTED_IPS состоял только из loopback ({loopback}). "
            f"После фильтрации список пуст — все вебхуки ЮKassa были бы "
            f"отклонены. Настройте реальные IP ЮKassa в yookassa_ip.json "
            f"или в переменной YOOKASSA_TRUSTED_IPS в .env."
        )

    settings.YOOKASSA_TRUSTED_IPS = filtered
    logger.info(
        f"YOOKASSA_TRUSTED_IPS: удалено {len(loopback)} loopback-записей, "
        f"осталось {len(filtered)}."
    )


_check_proxy_safety()