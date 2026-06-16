import asyncio
import logging
from typing import Optional, List, Dict

from db.models import VPNServer
from db.crud_servers import get_active_servers
from services.vpn_provider import XUIVPNProvider
from utils.encryption import decrypt_password

logger = logging.getLogger(__name__)

class ServerPool:
    def __init__(self):
        self.servers: List[VPNServer] = []
        self.providers: Dict[int, XUIVPNProvider] = {}
        self.current_index = 0
        self._lock = asyncio.Lock()
        self._login_tasks: Dict[int, asyncio.Task] = {}

    async def refresh_servers(self, wait_for_login: bool = True, login_timeout: float = 10.0):
        """Загрузить активные серверы из БД и создать провайдеров.
        
        Args:
            wait_for_login: Если True, дожидается успешного логина всех провайдеров (с таймаутом).
            login_timeout: Максимальное время ожидания логина для одного провайдера.
        """
        async with self._lock:
            # Отменяем незавершённые задачи логина (если перезагружаем пул)
            for task in self._login_tasks.values():
                if not task.done():
                    task.cancel()
            self._login_tasks.clear()

            new_servers = await get_active_servers()
            self.servers = new_servers

            # Удаляем провайдеров для серверов, которых больше нет
            old_ids = set(self.providers.keys())
            current_ids = {s.id for s in self.servers}
            for sid in old_ids - current_ids:
                provider = self.providers.pop(sid, None)
                if provider:
                    await provider.close()

            # Добавляем новых провайдеров
            for s in self.servers:
                if s.id not in self.providers:
                    real_password = decrypt_password(s.password)
                    # Все параметры берутся из БД
                    provider = XUIVPNProvider(
                        base_url=f"https://{s.host}:{s.port}{s.api_path or ''}",
                        username=s.username,
                        password=real_password,
                        inbound_id=s.inbound_id,
                        sub_port=s.sub_port
                    )
                    self.providers[s.id] = provider
                    
                    # Запускаем логин в фоне, но с возможностью дождаться
                    login_task = asyncio.create_task(self._login_provider_with_retry(s.id))
                    self._login_tasks[s.id] = login_task

            # Если требуется дождаться логина – ждём завершения всех задач (с таймаутом)
            if wait_for_login and self._login_tasks:
                logger.info(f"Waiting for {len(self._login_tasks)} providers to log in...")
                done, pending = await asyncio.wait(
                    self._login_tasks.values(),
                    timeout=login_timeout,
                    return_when=asyncio.ALL_COMPLETED
                )
                for task in pending:
                    task.cancel()
                    logger.warning(f"Login timeout for some provider, will retry on first use")
                for task in done:
                    if task.exception():
                        logger.error(f"Login failed: {task.exception()}")
                logger.info(f"Login completed: {len(done)} succeeded, {len(pending)} pending")

    async def _login_provider_with_retry(self, server_id: int, max_retries: int = 3):
        """Пытается залогиниться с повторными попытками."""
        provider = self.providers.get(server_id)
        if not provider:
            return
        for attempt in range(max_retries):
            try:
                if await provider.login():
                    logger.info(f"Provider {server_id} authenticated (attempt {attempt+1})")
                    return
                else:
                    logger.warning(f"Provider {server_id} login failed (attempt {attempt+1})")
            except Exception as e:
                logger.error(f"Provider {server_id} login error: {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
        logger.error(f"Provider {server_id} could not authenticate after {max_retries} attempts")

    async def get_server(self) -> Optional[VPNServer]:
        """Выбрать сервер round‑robin с учётом веса."""
        if not self.servers:
            await self.refresh_servers(wait_for_login=False)  # не блокируем при выборе
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
        """Возвращает провайдера, при необходимости дожидаясь его логина (но не блокируя надолго)."""
        provider = self.providers.get(server_id)
        if provider and not provider._is_authenticated:
            # Если провайдер ещё не залогинился, пытаемся залогиниться синхронно
            logger.info(f"Provider {server_id} not authenticated yet, logging in now...")
            try:
                await asyncio.wait_for(provider.login(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.error(f"Provider {server_id} login timeout")
            except Exception as e:
                logger.error(f"Provider {server_id} login error: {e}")
        return provider

    async def close_all(self):
        """Закрыть всех провайдеров и отменить задачи логина."""
        for task in self._login_tasks.values():
            if not task.done():
                task.cancel()
        # Даём задачам шанс завершиться
        await asyncio.sleep(0.1)
        for provider in self.providers.values():
            await provider.close()
        self.providers.clear()
        self.servers.clear()