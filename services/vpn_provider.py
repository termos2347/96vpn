import uuid
import logging
import asyncio
import aiohttp
import ssl
from typing import Optional, Dict, Any

from config import settings

logger = logging.getLogger(__name__)


class XUIVPNProvider:
    MAX_RETRIES = 3
    RETRY_DELAY = 1
    REQUEST_TIMEOUT = 30

    def __init__(self, base_url: str, api_token: str, inbound_id: int, sub_port: int):
        self.base_url = base_url.rstrip('/')
        self.api_token = api_token
        self.inbound_id = inbound_id
        self.sub_port = sub_port

        if not self.api_token:
            raise ValueError("API token is required for XUIVPNProvider")

        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_token}"
        }

        self._session: Optional[aiohttp.ClientSession] = None
        self._session_lock = asyncio.Lock()
        self._session_invalid = False
        self._closed = False

        self._server_host = self._extract_host(self.base_url)

    @staticmethod
    def _extract_host(url: str) -> str:
        try:
            parts = url.split("://")[1].split("/")[0].split(":")[0]
            return parts
        except (IndexError, AttributeError):
            logger.error(f"Failed to extract host from URL: {url}")
            return ""

    def _ssl_context(self):
        if not settings.VERIFY_SSL:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            return ctx
        return None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._closed:
            raise RuntimeError("Provider is closed")
        async with self._session_lock:
            if self._session is None or self._session.closed or self._session_invalid:
                if self._session and not self._session.closed:
                    await self._session.close()
                connector = aiohttp.TCPConnector(ssl=self._ssl_context(), limit=100, force_close=True)
                timeout = aiohttp.ClientTimeout(total=self.REQUEST_TIMEOUT)
                self._session = aiohttp.ClientSession(
                    connector=connector,
                    cookie_jar=aiohttp.CookieJar(unsafe=True),
                    timeout=timeout,
                    headers=self.headers
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
                kwargs.setdefault("headers", {})["Authorization"] = f"Bearer {self.api_token}"
                method_func = getattr(session, method.lower())
                async with method_func(url, **kwargs) as resp:
                    if resp.status == 200:
                        try:
                            return await resp.json()
                        except Exception:
                            return None
                    elif resp.status == 401:
                        logger.error("API token invalid or expired")
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

    async def create_client(self, email: str) -> Optional[Dict[str, str]]:
        """
        Создаёт клиента через /panel/api/clients/add.
        Возвращает словарь с uuid и subId.
        Ожидает email формата "user_{id}@96vpn.bot".
        """
        if not email:
            logger.error("Email is required")
            return None

        client_uuid = str(uuid.uuid4())
        # Извлекаем user_id из email "user_{id}@..."
        user_id = 0
        if email.startswith("user_"):
            try:
                user_id = int(email.split("_")[1].split("@")[0])
            except Exception:
                logger.warning(f"Could not parse user_id from email {email}")
        else:
            # fallback: генерируем хэш
            user_id = hash(email) % 1000000

        client_email = f"tg_{user_id}_{client_uuid[:8]}"
        sub_id = client_uuid[:16]

        payload = {
            "inboundIds": [self.inbound_id],
            "client": {
                "id": client_uuid,
                "email": client_email,
                "flow": "",
                "limitIp": 2,
                "totalGB": 0,
                "expiryTime": 0,
                "enable": True,
                "tgId": user_id,          # важно: число, не строка
                "subId": sub_id
            }
        }

        url = f"{self.base_url}/panel/api/clients/add"
        logger.info(f"Creating client with email {client_email} via {url}")

        try:
            result = await self._retry_request("POST", url, json=payload)
            if result and result.get("success") is True:
                logger.info(f"Client {client_email} created successfully, sub_id={sub_id}")
                return {"uuid": client_uuid, "subId": sub_id}
            else:
                logger.error(f"Failed to create client: {result}")
                return None
        except Exception as e:
            logger.exception(f"Exception creating client: {e}")
            return None

    async def get_client_by_email(self, email: str) -> Optional[Dict[str, str]]:
        url = f"{self.base_url}/panel/api/clients/get/{email}"
        try:
            result = await self._retry_request("GET", url)
            if result and result.get("success"):
                data = result.get("obj")
                if data:
                    return {
                        "uuid": data.get("id"),
                        "subId": data.get("subId"),
                        "email": data.get("email"),
                        "enable": data.get("enable"),
                    }
            return None
        except Exception as e:
            logger.exception(f"Error getting client by email {email}: {e}")
            return None

    async def get_client_by_uuid(self, client_uuid: str) -> Optional[Dict[str, str]]:
        logger.warning("get_client_by_uuid is not implemented")
        return None

    def get_subscription_link(self, sub_id: str) -> str:
        if not self._server_host or not sub_id:
            logger.error("Invalid server host or sub_id")
            return ""
        return f"https://{self._server_host}:{self.sub_port}/sub/{sub_id}"

    async def revoke_client(self, client_uuid: str) -> bool:
        url = f"{self.base_url}/panel/api/clients/del/{client_uuid}"
        try:
            result = await self._retry_request("POST", url)
            if result and result.get("success") is True:
                logger.info(f"Client {client_uuid} revoked")
                return True
            else:
                logger.error(f"Failed to revoke client {client_uuid}: {result}")
                return False
        except Exception as e:
            logger.exception(f"Error revoking client {client_uuid}: {e}")
            return False