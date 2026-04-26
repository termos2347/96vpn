import pytest
import asyncio
from datetime import datetime, timedelta
from db.crud import get_or_create_user, set_vpn_subscription, is_vpn_active, set_vpn_client_id
from db.base import init_db, AsyncSessionLocal
from db.models import User
from sqlalchemy import select

@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="session")
async def setup_database():
    """Initialize database before tests."""
    await init_db()

@pytest.mark.asyncio
async def test_get_or_create_user():
    """Test get_or_create_user function."""
    user_id = 123456789
    username = "test_user"

    # Create user
    user = await get_or_create_user(user_id, username)
    assert user is not None
    assert user.user_id == user_id
    assert user.username == username

    # Get existing user
    user2 = await get_or_create_user(user_id, "new_username")
    assert user2.user_id == user_id
    assert user2.username == username  # Should not change

@pytest.mark.asyncio
async def test_set_vpn_subscription():
    """Test set_vpn_subscription function."""
    user_id = 987654321

    # Create user first
    await get_or_create_user(user_id)

    # Set subscription for 30 days
    success = await set_vpn_subscription(user_id, 30)
    assert success is True

    # Check if active
    active = await is_vpn_active(user_id)
    assert active is True

    # Check end date
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.user_id == user_id))
        user = result.scalar_one()
        expected_end = datetime.now() + timedelta(days=30)
        assert abs((user.vpn_subscription_end - expected_end).total_seconds()) < 60  # within 1 minute

@pytest.mark.asyncio
async def test_set_vpn_client_id():
    """Test set_vpn_client_id function."""
    user_id = 111111111
    client_id = "test_client_uuid"

    # Create user
    await get_or_create_user(user_id)

    # Set client ID
    success = await set_vpn_client_id(user_id, client_id)
    assert success is True

    # Verify
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.user_id == user_id))
        user = result.scalar_one()
        assert user.vpn_client_id == client_id

    # Clear client ID
    success = await set_vpn_client_id(user_id, None)
    assert success is True

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.user_id == user_id))
        user = result.scalar_one()
        assert user.vpn_client_id is None