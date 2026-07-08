import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import text

from db.base import AsyncSessionLocal, retry_db_operation
from db.crud import get_or_create_bot_user
from services.vpn_provider import XUIVPNProvider

logger = logging.getLogger(__name__)


class VPNManager:
    def __init__(self, provider: XUIVPNProvider):
        self.provider = provider

    @retry_db_operation(max_retries=3)
    async def create_key(self, user_id: int, days: int) -> Optional[str]:
        email = f"user_{user_id}@96vpn.bot"

        try:
            client_data = await asyncio.wait_for(
                self.provider.create_client(email),
                timeout=15.0
            )
        except asyncio.TimeoutError:
            logger.error(f"Timeout creating client for user {user_id}")
            return None
        except Exception as e:
            logger.exception(f"Error creating client for user {user_id}: {e}")
            return None

        if not client_data:
            logger.error(f"Failed to create client for user {user_id}")
            return None

        client_uuid = client_data['uuid']
        sub_id = client_data['subId']
        link = self.provider.get_subscription_link(sub_id)

        async with AsyncSessionLocal() as session:
            async with session.begin():  # автоматический commit/rollback
                user = await get_or_create_bot_user(session, user_id)
                user.vpn_client_id = client_uuid
                now = datetime.now(timezone.utc)
                if user.vpn_subscription_end is None or user.vpn_subscription_end <= now:
                    user.vpn_subscription_end = now + timedelta(days=days)
                else:
                    user.vpn_subscription_end += timedelta(days=days)
                # commit автоматически при выходе из блока
                logger.info(f"Key created and DB updated for user {user_id}: {link}")
                return link

    @retry_db_operation(max_retries=3)
    async def get_or_create_link(self, user_id: int) -> Optional[str]:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                user = await get_or_create_bot_user(session, user_id)
                now = datetime.now(timezone.utc)
                if user.vpn_subscription_end is None or user.vpn_subscription_end <= now:
                    logger.info(f"User {user_id} has no active subscription")
                    return None
                if user.vpn_client_id:
                    client = await self.provider.get_client_by_uuid(user.vpn_client_id)
                    if client and client.get("subId"):
                        link = self.provider.get_subscription_link(client["subId"])
                        logger.info(f"Existing key for user {user_id}: {link}")
                        return link
                    else:
                        logger.warning(f"Stored client_id {user.vpn_client_id} not found on panel, will recreate")
                        user.vpn_client_id = None
                        # commit внутри блока

        days = (user.vpn_subscription_end - now).days
        if days < 1:
            days = 30
        return await self.create_key(user_id, days)

    @retry_db_operation(max_retries=3)
    async def revoke_key(self, user_id: int) -> bool:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                user = await get_or_create_bot_user(session, user_id)
                client_uuid = user.vpn_client_id
                if not client_uuid:
                    logger.info(f"User {user_id} has no active key to revoke")
                    return True

        try:
            success = await asyncio.wait_for(
                self.provider.revoke_client(client_uuid),
                timeout=15.0
            )
            if not success:
                client = await self.provider.get_client_by_uuid(client_uuid)
                if client is None:
                    logger.info(f"Client {client_uuid} not found on panel, assuming already revoked")
                else:
                    logger.error(f"Failed to revoke client {client_uuid} for user {user_id}")
                    return False
        except Exception as e:
            logger.exception(f"Error revoking client {client_uuid} for user {user_id}: {e}")
            return False

        async with AsyncSessionLocal() as session:
            async with session.begin():
                user = await get_or_create_bot_user(session, user_id)
                user.vpn_client_id = None
                user.vpn_subscription_end = datetime.now(timezone.utc) - timedelta(days=1)
                logger.info(f"Key revoked for user {user_id}")
                return True