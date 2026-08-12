import asyncio
import logging
import ssl
import uuid
from typing import Any

import aiohttp

from config import settings

logger = logging.getLogger(__name__)


class XUIVPNProvider:
    MAX_RETRIES = 3
    RETRY_DELAY = 1
    REQUEST_TIMEOUT = 30

    def __init__(self, base_url: str, api_token: str, inbound_id: int, sub_port: int):
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        self.inbound_id = inbound_id
        self.sub_port = sub_port

        if not self.api_token:
            raise ValueError("API token is required for XUIVPNProvider")

        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_token}",
        }

        self._session: aiohttp.ClientSession | None = None
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
                connector = aiohttp.TCPConnector(
                    ssl=self._ssl_context(), limit=100, force_close=True
                )
                timeout = aiohttp.ClientTimeout(total=self.REQUEST_TIMEOUT)
                self._session = aiohttp.ClientSession(
                    connector=connector,
                    cookie_jar=aiohttp.CookieJar(unsafe=True),
                    timeout=timeout,
                    headers=self.headers,
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

    async def _retry_request(
        self, method: str, url: str, **kwargs
    ) -> dict[str, Any] | None:
        attempt = 0
        while attempt < self.MAX_RETRIES:
            try:
                session = await self._get_session()
                kwargs.setdefault("headers", {})["Authorization"] = (
                    f"Bearer {self.api_token}"
                )
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
                        logger.warning(
                            f"HTTP {resp.status} from {url}, attempt {attempt + 1}"
                        )
            except (asyncio.TimeoutError, aiohttp.ClientError) as net_err:
                logger.warning(
                    f"Network error on {url} (attempt {attempt + 1}): {type(net_err).__name__}"
                )
                self._session_invalid = True
            except Exception:
                logger.exception(f"Unexpected error on {url}, attempt {attempt + 1}")

            attempt += 1
            if attempt < self.MAX_RETRIES:
                await asyncio.sleep(self.RETRY_DELAY * (2 ** (attempt - 1)))
        logger.error(
            f"Failed to {method.upper()} {url} after {self.MAX_RETRIES} attempts"
        )
        return None

    async def create_client(self, email: str, sub_id: str) -> dict[str, str] | None:
        if not email or not sub_id:
            logger.error("Email and sub_id are required")
            return None

        client_uuid = str(uuid.uuid4())
        user_id = 0
        if email.startswith("tg_"):
            try:
                parts = email.split("_")
                user_id = int(parts[1])
            except Exception:
                logger.warning(f"Could not parse user_id from email {email}")
        else:
            user_id = hash(email) % 1000000

        payload = {
            "inboundIds": [self.inbound_id],
            "client": {
                "id": client_uuid,
                "email": email,
                "flow": "",
                "limitIp": 2,
                "totalGB": 0,
                "expiryTime": 0,
                "enable": True,
                "tgId": user_id,
                "subId": sub_id,
            },
        }

        url = f"{self.base_url}/panel/api/clients/add"
        logger.info(f"Creating client with email {email}, subId={sub_id} via {url}")

        try:
            result = await self._retry_request("POST", url, json=payload)
            if result and result.get("success") is True:
                logger.info(f"Client {email} created successfully with subId={sub_id}")
                return {"uuid": client_uuid, "subId": sub_id}
            else:
                logger.error(f"Failed to create client: {result}")
                return None
        except Exception:
            logger.exception("Exception creating client")
            return None

    async def get_client_by_email(self, email: str) -> dict[str, str] | None:
        """
        Ищет клиента по email.
        Пытается извлечь subId из разных полей ответа.
        """
        url = f"{self.base_url}/panel/api/clients/get/{email}"
        try:
            result = await self._retry_request("GET", url)
            logger.debug(f"get_client_by_email response for {email}: {result}")
            if result and result.get("success"):
                data = result.get("obj")
                if data:
                    # Пробуем найти subId в разных местах
                    sub_id = (
                        data.get("subId") or data.get("subid") or data.get("sub_id")
                    )
                    client_uuid = data.get("id") or data.get("uuid")
                    client_email = data.get("email")
                    enable = data.get("enable")

                    # Если sub_id не найден, возможно, клиент вложен в "client"
                    if sub_id is None and "client" in data:
                        client_obj = data["client"]
                        sub_id = (
                            client_obj.get("subId")
                            or client_obj.get("subid")
                            or client_obj.get("sub_id")
                        )
                        client_uuid = client_obj.get("id") or client_obj.get("uuid")
                        client_email = client_obj.get("email")
                        enable = client_obj.get("enable")

                    if sub_id:
                        return {
                            "uuid": client_uuid,
                            "subId": sub_id,
                            "email": client_email,
                            "enable": enable,
                        }
                    else:
                        logger.warning(f"Client found but no subId in response: {data}")
                        return None
            return None
        except Exception:
            logger.exception(f"Error getting client by email {email}")
            return None

    async def get_client_by_sub_id(self, sub_id: str) -> dict[str, str] | None:
        """
        Пытается найти клиента по subId через эндпоинт /getSub/{subId}.
        Выполняет только одну попытку (без ретраев), так как эндпоинт часто недоступен.
        """
        if not sub_id:
            return None

        # Обрезаем до 16 символов, если передан полный UUID
        if len(sub_id) > 16:
            original = sub_id
            sub_id = sub_id[:16]
            logger.debug(f"Trimmed subId from '{original}' to '{sub_id}'")

        url = f"{self.base_url}/panel/api/clients/getSub/{sub_id}"
        try:
            session = await self._get_session()
            async with session.get(url, headers=self.headers) as resp:
                if resp.status == 200:
                    try:
                        result = await resp.json()
                        if result and result.get("success"):
                            data = result.get("obj")
                            if data:
                                sub_id_from_resp = (
                                    data.get("subId")
                                    or data.get("subid")
                                    or data.get("sub_id")
                                )
                                if sub_id_from_resp:
                                    return {
                                        "uuid": data.get("id") or data.get("uuid"),
                                        "subId": sub_id_from_resp,
                                        "email": data.get("email"),
                                        "enable": data.get("enable"),
                                    }
                    except Exception:
                        logger.exception(
                            "Ошибка в get_client_by_sub_id при парсинге ответа"
                        )
                elif resp.status == 404:
                    logger.debug(f"Client with subId {sub_id} not found (404)")
                else:
                    logger.warning(f"HTTP {resp.status} from {url}")
            return None
        except Exception as e:
            logger.warning(f"getSub endpoint failed: {e}")
            return None

    async def get_all_clients(self) -> list[dict]:
        """Получает список всех клиентов (используется как fallback)."""
        url = f"{self.base_url}/panel/api/clients"
        try:
            result = await self._retry_request("GET", url)
            if result and result.get("success"):
                return result.get("obj", [])
            return []
        except Exception:
            logger.exception("Error getting all clients")
            return []

    def get_subscription_link(self, sub_id: str) -> str:
        if not self._server_host or not sub_id:
            logger.error("Invalid server host or sub_id")
            return ""
        return f"https://{self._server_host}:{self.sub_port}/sub/{sub_id}"

    async def revoke_client(self, sub_id: str) -> bool:
        url = f"{self.base_url}/panel/api/clients/delSub/{sub_id}"
        try:
            result = await self._retry_request("POST", url)
            if result and result.get("success") is True:
                logger.info(f"Client with subId {sub_id} revoked")
                return True
            else:
                logger.warning(f"Failed to revoke by subId, result: {result}")
                return False
        except Exception:
            logger.exception(f"Error revoking client by subId {sub_id}")
            return False
