import uuid
import json
import logging
import asyncio
import aiohttp
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class XUIVPNProvider:
    MAX_RETRIES = 3
    RETRY_DELAY = 1
    REQUEST_TIMEOUT = 30
    HEARTBEAT_INTERVAL = 300  # 5 минут – можно убрать, если не нужен keep-alive

    def __init__(self, base_url: str, username: str, password: str,
                 inbound_id: int, sub_port: int):
        self.base_url = base_url.rstrip('/')
        self.username = username
        self.password = password
        self.inbound_id = inbound_id
        self.sub_port = sub_port

        self.headers = {"Referer": f"{self.base_url}/panel/inbounds"}
        self._session: Optional[aiohttp.ClientSession] = None
        self._session_lock = asyncio.Lock()
        self._session_invalid = False
        self._is_authenticated = False
        self._closed = False

        # Извлекаем хост для подписки (без порта)
        self._server_host = self._extract_host(self.base_url)

    @staticmethod
    def _extract_host(url: str) -> str:
        try:
            parts = url.split("://")[1].split("/")[0].split(":")[0]
            return parts
        except (IndexError, AttributeError):
            logger.error(f"Failed to extract host from URL: {url}")
            return ""

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._closed:
            raise RuntimeError("Provider is closed")
        async with self._session_lock:
            if self._session is None or self._session.closed or self._session_invalid:
                if self._session and not self._session.closed:
                    await self._session.close()
                connector = aiohttp.TCPConnector(ssl=True, limit=100, force_close=True)
                timeout = aiohttp.ClientTimeout(total=self.REQUEST_TIMEOUT)
                self._session = aiohttp.ClientSession(
                    connector=connector,
                    cookie_jar=aiohttp.CookieJar(unsafe=True),
                    timeout=timeout
                )
                self._session_invalid = False
                logger.debug(f"Created new session for {self.base_url}")
            return self._session

    async def close(self):
        self._closed = True
        async with self._session_lock:
            if self._session and not self._session.closed:
                await self._session.close()
                self._session = None
        logger.info(f"XUI provider closed for {self.base_url}")

    async def _retry_request(self, method: str, url: str, **kwargs) -> Optional[Dict[str, Any]]:
        attempt = 0
        last_error = None
        while attempt < self.MAX_RETRIES:
            try:
                session = await self._get_session()
                method_func = getattr(session, method.lower())
                async with method_func(url, **kwargs) as resp:
                    if resp.status == 200:
                        try:
                            return await resp.json()
                        except Exception:
                            return None
                    elif resp.status == 401:
                        self._is_authenticated = False
                        if await self.login():
                            continue
                        else:
                            return None
                    else:
                        logger.warning(f"HTTP {resp.status} from {url}, attempt {attempt+1}")
            except (asyncio.TimeoutError, aiohttp.ClientError) as net_err:
                logger.warning(f"Network error on {url} (attempt {attempt+1}): {type(net_err).__name__}")
                self._session_invalid = True
                last_error = net_err
            except Exception as e:
                logger.exception(f"Unexpected error on {url}, attempt {attempt+1}")
                last_error = e

            attempt += 1
            if attempt < self.MAX_RETRIES:
                await asyncio.sleep(self.RETRY_DELAY * (2 ** (attempt - 1)))
        logger.error(f"Failed to {method.upper()} {url} after {self.MAX_RETRIES} attempts")
        return None

    async def login(self) -> bool:
        if self._is_authenticated:
            return True
        url = f"{self.base_url}/login"
        payload = {"username": self.username, "password": self.password}
        try:
            session = await self._get_session()
            async with session.post(url, data=payload) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    if result and result.get("success"):
                        self._is_authenticated = True
                        logger.info(f"Authenticated with {self.base_url}")
                        return True
                    else:
                        logger.error(f"Auth failed: {result.get('msg')}")
                        return False
                else:
                    logger.error(f"Login HTTP {resp.status}")
                    return False
        except Exception as e:
            logger.exception(f"Login exception for {self.base_url}")
            return False

    async def create_client(self, email: str) -> Optional[Dict[str, str]]:
        if not await self.login():
            logger.error("Cannot create client: not authenticated")
            return None

        client_uuid = str(uuid.uuid4())
        sub_id = str(uuid.uuid4()).replace('-', '')[:16]

        settings_data = {
            "clients": [{
                "id": client_uuid,
                "email": email,
                "alterId": 0,
                "limitIp": 1,
                "totalGb": 0,
                "expiryTime": 0,
                "enable": True,
                "tgId": "",
                "subId": sub_id,
                "flow": "xtls-rprx-vision"
            }]
        }

        payload = {
            "id": self.inbound_id,
            "settings": json.dumps(settings_data)
        }
        url = f"{self.base_url}/panel/api/inbounds/addClient"

        try:
            result = await self._retry_request("POST", url, data=payload, headers=self.headers)
            if result and result.get("success"):
                logger.info(f"Client {email} created with UUID {client_uuid}")
                return {"uuid": client_uuid, "subId": sub_id}
            elif result and "Duplicate" in result.get("msg", ""):
                logger.warning(f"Email {email} already exists on panel")
                return None
            else:
                logger.error(f"Failed to create client: {result.get('msg') if result else 'No response'}")
                return None
        except Exception:
            logger.exception("Exception creating client")
            return None

    async def get_client_by_email(self, email: str) -> Optional[Dict[str, str]]:
        if not await self.login():
            return None
        url = f"{self.base_url}/panel/api/inbounds/get/{self.inbound_id}"
        try:
            result = await self._retry_request("GET", url, headers=self.headers)
            if not result:
                return None
            inbound = result.get("obj")
            if not inbound:
                return None
            settings_data = json.loads(inbound.get("settings", "{}"))
            for client in settings_data.get("clients", []):
                if client.get("email") == email:
                    return {
                        "uuid": client.get("id"),
                        "subId": client.get("subId", client.get("id")[:16])
                    }
            return None
        except Exception:
            logger.exception("Exception searching client by email")
            return None

    async def get_client_by_uuid(self, client_uuid: str) -> Optional[Dict[str, str]]:
        if not await self.login():
            return None
        url = f"{self.base_url}/panel/api/inbounds/get/{self.inbound_id}"
        try:
            result = await self._retry_request("GET", url, headers=self.headers)
            if not result:
                return None
            inbound = result.get("obj")
            if not inbound:
                return None
            settings_data = json.loads(inbound.get("settings", "{}"))
            for client in settings_data.get("clients", []):
                if client.get("id") == client_uuid:
                    return {
                        "uuid": client.get("id"),
                        "subId": client.get("subId", client.get("id")[:16]),
                        "email": client.get("email")
                    }
            return None
        except Exception:
            logger.exception("Exception searching client by uuid")
            return None

    def get_subscription_link(self, sub_id: str) -> str:
        if not self._server_host or not sub_id:
            logger.error("Invalid server host or sub_id")
            return ""
        return f"https://{self._server_host}:{self.sub_port}/sub/{sub_id}"

    async def revoke_client(self, client_uuid: str) -> bool:
        if not await self.login():
            logger.error("Cannot revoke client: not authenticated")
            return False
        # Пробуем разные варианты URL
        endpoints = [
            f"{self.base_url}/panel/api/inbounds/{self.inbound_id}/delClient/{client_uuid}",
            f"{self.base_url}/panel/api/inbounds/delClient/{self.inbound_id}/Client/{client_uuid}",
        ]
        for url in endpoints:
            try:
                result = await self._retry_request("POST", url, headers=self.headers)
                if result and result.get("success"):
                    logger.info(f"Client {client_uuid} revoked successfully")
                    return True
            except Exception as e:
                logger.debug(f"Failed endpoint {url}: {e}")
                continue
        logger.error(f"Failed to revoke client {client_uuid}")
        return False