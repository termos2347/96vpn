# tests/conftest.py
"""
Общие фикстуры для тестов.

ВАЖНО: env-переменные выставляются на уровне модуля ДО первого импорта
`config` — иначе pydantic-settings попытается прочитать боевой `.env`
(или упадёт с ValidationError, если его нет).
"""
import os

# --- Обязательные переменные для Settings (см. config.py) ---
os.environ.setdefault("BOT_TOKEN", "123456:TEST_MAIN_BOT_TOKEN")
os.environ.setdefault("ADMIN_BOT_TOKEN", "123456:TEST_ADMIN_BOT_TOKEN")
os.environ.setdefault("ADMIN_CHAT_ID", "123456789")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test_db"
)

os.environ.setdefault("WEBHOOK_URL", "http://localhost:5001/webhook")
os.environ.setdefault("WEBHOOK_SECRET", "test_webhook_secret_0123456789")
os.environ.setdefault("ADMIN_WEBHOOK_URL", "http://localhost:5001/webhook/admin")
os.environ.setdefault(
    "ADMIN_WEBHOOK_SECRET", "test_admin_webhook_secret_0123456789"
)

os.environ.setdefault(
    "ENCRYPTION_KEY", "dGVzdF9mZXJuZXRfa2V5X2Zvcl90ZXN0c19vbmx5Xz0="
)
# BUGFIX: config.py требует min_length=32 для INTERNAL_API_SECRET.
# Раньше здесь был "test_internal_api_secret" (24 символа) — тесты
# падали бы с ValidationError на импорте config (sys.exit(1)).
os.environ.setdefault(
    "INTERNAL_API_SECRET", "test_internal_api_secret_0123456789abcdef"
)

os.environ.setdefault("YOOKASSA_SHOP_ID", "123456")
os.environ.setdefault("YOOKASSA_API_KEY", "test_" + "x" * 40)
os.environ.setdefault("YOOKASSA_TRUSTED_IPS", '["127.0.0.1", "185.71.76.0/24"]')

# Прокси по умолчанию — localhost (в тестах всё через TestServer)
os.environ.setdefault("TRUSTED_PROXY_IPS", '["127.0.0.1", "::1"]')

os.environ.setdefault("XUI_MASTER_URL", "http://localhost:2053")
os.environ.setdefault("XUI_API_TOKEN", "test_xui_token_0123456789abcdef")
os.environ.setdefault("XUI_INBOUND_ID", "1")
os.environ.setdefault("XUI_SUB_PORT", "2096")

os.environ.setdefault("REDIS_ENABLED", "false")
os.environ.setdefault("SKIP_MIGRATION_CHECK", "true")
os.environ.setdefault("DEBUG", "true")

# --- Теперь безопасно импортировать проект ---
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models import Base
from services.vpn_provider import XUIVPNProvider


@pytest.fixture(autouse=True)
def clear_memory_cache():
    """Сбрасывает in-memory кэш и rate limit между тестами.

    utils/cache.py хранит данные в глобальном словаре — без этой
    фикстуры тесты могут «протекать» друг в друга (особенно
    test_rate_limit_* и test_vpn_manager, где user_id пересекаются).
    """
    from utils.cache import clear_cache

    clear_cache()
    yield
    clear_cache()


@pytest.fixture(autouse=True)
def clean_pending_key_tasks():
    """Чистка fire-and-forget задач между тестами (глобальный set в
    services.payment_yookassa). Раньше фикстура была в test_core.py и
    не покрывала test_payment.py — отсюда flaky.
    """
    from services import payment_yookassa as yk

    yield

    for task in list(yk._pending_key_tasks):
        if not task.done():
            task.cancel()
    yk._pending_key_tasks.clear()


@pytest.fixture(scope="function")
async def test_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture(scope="function")
async def test_session(test_engine):
    session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session


@pytest.fixture
def mock_yookassa_payment():
    with patch("services.payment_yookassa.Payment") as mock_payment_class:
        mock_create = MagicMock()
        mock_find = MagicMock()
        payment_mock = MagicMock()
        payment_mock.id = "test_payment_123"
        payment_mock.status = "pending"
        payment_mock.confirmation = MagicMock()
        payment_mock.confirmation.confirmation_url = "https://yookassa.ru/confirm"
        payment_mock.amount = MagicMock(value="100.00", currency="RUB")
        mock_create.return_value = payment_mock
        mock_find.return_value = payment_mock
        mock_payment_class.create = mock_create
        mock_payment_class.find_one = mock_find
        yield mock_payment_class


@pytest.fixture
def mock_bot():
    bot = AsyncMock(spec=Bot)
    bot.send_message = AsyncMock()
    bot.send_photo = AsyncMock()
    bot.send_document = AsyncMock()
    bot.send_video = AsyncMock()
    bot.send_animation = AsyncMock()
    return bot


@pytest.fixture
def mock_vpn_provider():
    provider = AsyncMock(spec=XUIVPNProvider)
    provider.create_client = AsyncMock(
        return_value={"uuid": "test-uuid", "subId": "test-sub"}
    )
    provider.revoke_client = AsyncMock(return_value=True)
    provider.get_client_by_email = AsyncMock(
        return_value={
            "uuid": "test-uuid",
            "subId": "test-sub",
            "email": "test@example.com",
        }
    )
    provider.get_client_by_sub_id = AsyncMock(
        return_value={
            "uuid": "test-uuid",
            "subId": "test-sub",
            "email": "test@example.com",
        }
    )
    provider.get_subscription_link = MagicMock(
        return_value="https://test.com/sub/test-sub"
    )
    return provider