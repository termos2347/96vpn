import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.base import AsyncSessionLocal, retry_db_operation
from db.models import BotUser
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
            async with session.begin():
                # Увеличиваем таймаут до 300 секунд
                await session.execute(text("SET LOCAL statement_timeout = '300s'"))

                now = datetime.now(timezone.utc)
                new_end = now + timedelta(days=days)

                result = await session.execute(
                    text("""
                        UPDATE bot_users
                        SET vpn_client_id = :client_id,
                            vpn_subscription_end = :end_date,
                            updated_at = :updated_at
                        WHERE telegram_id = :tg_id
                    """),
                    {
                        "client_id": client_uuid,
                        "end_date": new_end,
                        "updated_at": now,
                        "tg_id": user_id
                    }
                )

                if result.rowcount == 0:
                    await session.execute(
                        text("""
                            INSERT INTO bot_users (telegram_id, vpn_client_id, vpn_subscription_end, updated_at, created_at)
                            VALUES (:tg_id, :client_id, :end_date, :updated_at, :updated_at)
                            ON CONFLICT (telegram_id) DO UPDATE
                            SET vpn_client_id = EXCLUDED.vpn_client_id,
                                vpn_subscription_end = EXCLUDED.vpn_subscription_end,
                                updated_at = EXCLUDED.updated_at
                        """),
                        {
                            "tg_id": user_id,
                            "client_id": client_uuid,
                            "end_date": new_end,
                            "updated_at": now
                        }
                    )

                await session.commit()
                logger.info(f"Key created and DB updated for user {user_id}: {link}")
                return link

    @retry_db_operation(max_retries=3)
    async def get_or_create_link(self, user_id: int) -> Optional[str]:
        async with AsyncSessionLocal() as session:
            row = await session.execute(
                text("""
                    SELECT vpn_subscription_end, vpn_client_id
                    FROM bot_users
                    WHERE telegram_id = :tg_id
                """),
                {"tg_id": user_id}
            )
            result = row.first()
            now = datetime.now(timezone.utc)

            if result:
                vpn_end, client_uuid = result
                if vpn_end and vpn_end > now:
                    if client_uuid:
                        client = await self.provider.get_client_by_uuid(client_uuid)
                        if client and client.get("subId"):
                            link = self.provider.get_subscription_link(client["subId"])
                            logger.info(f"Existing key for user {user_id}: {link}")
                            return link
                        else:
                            await session.execute(
                                text("UPDATE bot_users SET vpn_client_id = NULL WHERE telegram_id = :tg_id"),
                                {"tg_id": user_id}
                            )
                            await session.commit()
                    days_left = (vpn_end - now).days
                    if days_left < 1:
                        days_left = 30
                    return await self.create_key(user_id, days_left)
                else:
                    logger.info(f"User {user_id} has no active subscription")
                    return None
            else:
                logger.info(f"User {user_id} not found, creating...")
                await session.execute(
                    text("""
                        INSERT INTO bot_users (telegram_id, created_at, updated_at)
                        VALUES (:tg_id, :now, :now)
                        ON CONFLICT (telegram_id) DO NOTHING
                    """),
                    {"tg_id": user_id, "now": now}
                )
                await session.commit()
                return None

    @retry_db_operation(max_retries=3)
    async def revoke_key(self, user_id: int) -> bool:
        async with AsyncSessionLocal() as session:
            row = await session.execute(
                text("SELECT vpn_client_id FROM bot_users WHERE telegram_id = :tg_id"),
                {"tg_id": user_id}
            )
            client_uuid = row.scalar()
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
        except asyncio.TimeoutError:
            logger.error(f"Timeout revoking client {client_uuid} for user {user_id}")
            return False
        except Exception as e:
            logger.exception(f"Error revoking client {client_uuid} for user {user_id}: {e}")
            return False

        async with AsyncSessionLocal() as session:
            async with session.begin():
                await session.execute(
                    text("""
                        UPDATE bot_users
                        SET vpn_client_id = NULL,
                            vpn_subscription_end = :end_date,
                            updated_at = :now
                        WHERE telegram_id = :tg_id
                    """),
                    {
                        "end_date": datetime.now(timezone.utc) - timedelta(days=1),
                        "now": datetime.now(timezone.utc),
                        "tg_id": user_id
                    }
                )
                await session.commit()
                logger.info(f"Key revoked for user {user_id}")
                return True