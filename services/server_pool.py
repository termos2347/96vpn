import asyncio
import logging
from typing import Optional, List
from urllib.parse import urlparse

from db.models import VPNServer
from db.crud_servers import get_active_servers
from services.vpn_provider import XUIVPNProvider

logger = logging.getLogger(__name__)

class ServerPool:
    def __init__(self):
        self.servers: List[VPNServer] = []
        self.providers: dict[int, XUIVPNProvider] = {}
        self.current_index = 0
        self._lock = asyncio.Lock()

    async def refresh_servers(self):
        """Загрузить активные серверы из БД и создать провайдеров."""
        async with self._lock:
            self.servers = await get_active_servers()
            for s in self.servers:
                if s.id not in self.providers:
                    # Собираем полный URL панели
                    base_url = f"https://{s.host}:{s.port}{s.api_path or ''}"
                    self.providers[s.id] = XUIVPNProvider(
                        base_url=base_url,
                        username=s.username,
                        password=s.password,
                        inbound_id=s.inbound_id,
                        sub_port=s.sub_port
                    )
                    asyncio.create_task(self._login_provider(s.id))

    async def _login_provider(self, server_id: int):
        provider = self.providers.get(server_id)
        if provider:
            try:
                await provider.login()
            except Exception as e:
                logger.warning(f"Failed to login to server {server_id}: {e}")

    async def get_server(self) -> Optional[VPNServer]:
        """Выбрать сервер round‑robin с учётом веса."""
        if not self.servers:
            await self.refresh_servers()
        if not self.servers:
            return None
        weighted = []
        for s in self.servers:
            weight = s.weight if s.weight is not None else 1
            weighted.extend([s] * weight)
        if not weighted:
            return None
        idx = self.current_index % len(weighted)
        self.current_index += 1
        return weighted[idx]

    async def get_provider(self, server_id: int) -> Optional[XUIVPNProvider]:
        return self.providers.get(server_id)

    async def close_all(self):
        for provider in self.providers.values():
            await provider.close()