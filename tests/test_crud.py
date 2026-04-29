import pytest
from db.crud import create_client, get_client, update_client, delete_client
from db.models import Client
from sqlalchemy.orm import Session
from db.base import SessionLocal

@pytest.fixture(scope="function")
def session() -> Session:
    # Create a new session for each test
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@pytest.mark.asyncio
async def test_crud_operations(session):
    # Create a client
    client = await create_client(user_id=1, email="test@example.com", username="test_user", session=session)
    assert client is not None
    assert client.email == "test@example.com"
    
    # Retrieve the client
    retrieved_client = get_client(client.id, session=session)
    assert retrieved_client is not None
    assert retrieved_client.email == "test@example.com"
    
    # Update the client
    updated = update_client(client.id, email="updated@example.com", username="updated_user", session=session)
    assert updated is True

    # Verify the update
    updated_client = get_client(client.id, session=session)
    assert updated_client.email == "updated@example.com"
    
    # Delete the client
    deleted = delete_client(client.id, session=session)
    assert deleted is True

    # Verify deletion
    deleted_client = get_client(client.id, session=session)
    assert deleted_client is None