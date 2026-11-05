# tests/test_core.py
"""Тесты инфраструктуры: internal API, scheduler, shutdown, валидаторы."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy.ext.asyncio import async_sessionmaker

from config import INTERNAL_API_SECRET
from db.models import BotUser
from internal_api import create_internal_app
from services import payment_yookassa as yk
from services.scheduler import check_expired_subscriptions
from utils.validators import (
    ValidationError,
    validate_currency,
    validate_days,
    validate_user_id,
    validate_uuid,
)


# ============================================================
# Internal API — /activate
# ============================================================


@pytest.fixture
def internal_app(mock_bot):
    return create_internal_app(
        main_bot=mock_bot, main_dp=None, admin_bot=None, admin_dp=None
    )


@pytest.fixture
async def client(internal_app):
    async with TestClient(TestServer(internal_app)) as c:
        yield c


@pytest.fixture
def patched_session_local(test_engine):
    session_maker = async_sessionmaker(test_engine, expire_on_commit=False)
    with patch("internal_api.AsyncSessionLocal", session_maker):
        yield session_maker


@pytest.mark.asyncio
async def test_activate_success(client, mock_bot, patched_session_local):
    payload = {
        "telegram_id": 123,
        "product_type": "vpn",
        "period": "1m",
        "payment_id": "test_pay",
    }
    headers = {"Authorization": f"Bearer {INTERNAL_API_SECRET}"}

    with patch(
        "internal_api.activate_subscription", new=AsyncMock(return_value=True)
    ) as mock_activate, patch("internal_api.get_vpn_manager") as mock_get_manager:
        mock_manager = AsyncMock()
        mock_manager.create_vpn_key = AsyncMock(
            return_value="https://test.com/sub/xyz"
        )
        mock_get_manager.return_value = mock_manager

        resp = await client.post("/activate", json=payload, headers=headers)
        assert resp.status == 200
        data = await resp.json()
        assert data == {"status": "ok"}

        mock_activate.assert_called_once()
        mock_manager.create_vpn_key.assert_called_once_with(123)
        mock_bot.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_activate_missing_fields(client):
    payload = {"telegram_id": 123}
    headers = {"Authorization": f"Bearer {INTERNAL_API_SECRET}"}
    resp = await client.post("/activate", json=payload, headers=headers)
    assert resp.status == 400
    data = await resp.json()
    assert "error" in data


@pytest.mark.asyncio
async def test_activate_unauthorized(client):
    payload = {"telegram_id": 123, "product_type": "vpn", "period": "1m"}
    resp = await client.post("/activate", json=payload)
    assert resp.status == 401


@pytest.mark.asyncio
async def test_activate_rejects_bypass(client):
    payload = {
        "telegram_id": 123,
        "product_type": "bypass",
        "period": "1m",
        "payment_id": "test_pay",
    }
    headers = {"Authorization": f"Bearer {INTERNAL_API_SECRET}"}
    resp = await client.post("/activate", json=payload, headers=headers)
    assert resp.status == 400
    data = await resp.json()
    assert "product_type" in data.get("error", "")


# ============================================================
# Scheduler
# ============================================================


@pytest.mark.asyncio
async def test_check_expired_subscriptions(test_engine, mock_bot):
    user_id = 123
    session_maker = async_sessionmaker(test_engine, expire_on_commit=False)

    async with session_maker() as s:
        async with s.begin():
            s.add(
                BotUser(
                    telegram_id=user_id,
                    vpn_subscription_end=datetime.now(timezone.utc)
                    - timedelta(days=1),
                    vpn_client_id="test-uuid",
                )
            )

    with patch("services.scheduler.AsyncSessionLocal", session_maker), patch(
        "services.scheduler.get_vpn_manager"
    ) as mock_get_manager:
        mock_manager = AsyncMock()
        mock_manager.revoke_key = AsyncMock(return_value=True)
        mock_get_manager.return_value = mock_manager

        await check_expired_subscriptions(mock_bot)

        mock_manager.revoke_key.assert_called_once_with(user_id)
        mock_bot.send_message.assert_called_once()


# ============================================================
# Shutdown — трекинг и отмена fire-and-forget задач
# ============================================================


@pytest.fixture(autouse=True)
def clean_tasks():
    yk._pending_key_tasks.clear()
    yield
    yk._pending_key_tasks.clear()


@pytest.mark.asyncio
async def test_schedule_tracks_task():
    async def dummy():
        await asyncio.sleep(10)

    task = yk._schedule_key_task(dummy())
    assert task in yk._pending_key_tasks

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_shutdown_cancels_tasks():
    started = []

    async def long_task():
        started.append(1)
        await asyncio.sleep(100)

    task1 = yk._schedule_key_task(long_task())
    task2 = yk._schedule_key_task(long_task())

    await asyncio.sleep(0)
    assert len(started) == 2

    await yk.shutdown_pending_tasks(timeout=1.0)

    assert task1.done()
    assert task2.done()
    assert len(yk._pending_key_tasks) == 0


@pytest.mark.asyncio
async def test_shutdown_empty_does_not_crash():
    await yk.shutdown_pending_tasks()
    assert len(yk._pending_key_tasks) == 0


@pytest.mark.asyncio
async def test_completed_task_removed_from_set():
    async def quick():
        return 42

    task = yk._schedule_key_task(quick())
    await task
    await asyncio.sleep(0)
    assert task not in yk._pending_key_tasks


@pytest.mark.asyncio
async def test_shutdown_with_already_done_task():
    async def quick():
        return 1

    task = yk._schedule_key_task(quick())
    await task
    await yk.shutdown_pending_tasks(timeout=1.0)


# ============================================================
# Validators
# ============================================================


def test_validate_user_id():
    assert validate_user_id(123)
    with pytest.raises(ValidationError):
        validate_user_id(0)


def test_validate_days():
    assert validate_days(30)
    with pytest.raises(ValidationError):
        validate_days(10)


def test_validate_currency():
    assert validate_currency("rub")
    for invalid in ("eur", "gbp", "RUB", "usd", ""):
        with pytest.raises(ValidationError):
            validate_currency(invalid)


def test_validate_uuid():
    assert validate_uuid("123e4567-e89b-12d3-a456-426614174000")
    with pytest.raises(ValidationError):
        validate_uuid("invalid-uuid")