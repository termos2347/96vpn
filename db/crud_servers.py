from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from db.base import AsyncSessionLocal
from db.models import VPNServer
from typing import Optional, List
import logging

logger = logging.getLogger(__name__)


async def add_server(
    name: str,
    host: str,
    port: int,
    inbound_id: int,
    username: str,
    password: str,
    api_path: str = "",
    sub_port: int = 2096,
    is_active: bool = True,
    weight: int = 1
) -> Optional[VPNServer]:
    async with AsyncSessionLocal() as session:
        existing = await session.execute(select(VPNServer).where(VPNServer.name == name))
        if existing.scalars().first():
            return None
        server = VPNServer(
            name=name, host=host, port=port, inbound_id=inbound_id,
            username=username, password=password, api_path=api_path,
            sub_port=sub_port, is_active=is_active, weight=weight
        )
        session.add(server)
        await session.commit()
        await session.refresh(server)
        return server


async def get_all_servers() -> List[VPNServer]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(VPNServer).order_by(VPNServer.name))
        return result.scalars().all()


async def get_active_servers() -> List[VPNServer]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(VPNServer).where(VPNServer.is_active == True))
        return result.scalars().all()


async def get_server_by_id(server_id: int) -> Optional[VPNServer]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(VPNServer).where(VPNServer.id == server_id))
        return result.scalars().first()


async def update_server(server_id: int, **kwargs) -> bool:
    async with AsyncSessionLocal() as session:
        stmt = update(VPNServer).where(VPNServer.id == server_id).values(**kwargs)
        result = await session.execute(stmt)
        await session.commit()
        return result.rowcount > 0


async def delete_server(server_id: int) -> bool:
    async with AsyncSessionLocal() as session:
        stmt = delete(VPNServer).where(VPNServer.id == server_id)
        result = await session.execute(stmt)
        await session.commit()
        return result.rowcount > 0