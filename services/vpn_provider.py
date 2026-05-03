import os
import uuid
import json
import logging
import asyncio
import aiohttp
from dotenv import load_dotenv
from config import XUI_BASE_URL, XUI_USERNAME, XUI_PASSWORD, XUI_INBOUND_ID, XUI_SUB_PORT

load_dotenv()
logger = logging.getLogger(__name__)

class XUIVPNProvider:
    MAX_RETRIES = 3
    RETRY_DELAY = 1
    REQUEST_TIMEOUT = 10

    def __init__(self):
        self.base_url = XUI_BASE_URL.rstrip('/') if XUI_BASE_URL else ""
        self.username = XUI_USERNAME
        self.password = XUI_PASSWORD
        self.inbound_id = XUI_INBOUND_ID
        self.sub_port = XUI_SUB_PORT
        self.headers = {"Referer": f"{self.base_url}/panel/inbounds"} if self.base_url else {}
        self.session = None
        self._server_address = self._extract_host(self.base_url) if self.base_url else ""
        self._is_authenticated = False

    @staticmethod
    def _extract_host(url: str) -> str:
        if not url:
            return ""
        try:
            parts = url.split("://")[1].split("/")[0].split(":")[0]
            return parts
        except (IndexError, AttributeError):
            logger.error(f"Failed to extract host from URL: {url}")
            return ""

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            connector = aiohttp.TCPConnector(ssl=False, limit=100)
            timeout = aiohttp.ClientTimeout(total=self.REQUEST_TIMEOUT)
            self.session = aiohttp.ClientSession(
                connector=connector,
                cookie_jar=aiohttp.CookieJar(unsafe=True),
                timeout=timeout
            )
        return self.session

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()
            logger.info("XUI provider session closed")

    async def _retry_request(self, method: str, url: str, **kwargs) -> dict | None:
        session = await self._get_session()
        attempt = 0
        while attempt < self.MAX_RETRIES:
            try:
                method_func = getattr(session, method.lower())
                async with method_func(url, **kwargs) as resp:
                    if resp.status == 200:
                        try:
                            return await resp.json()
                        except Exception:
                            logger.warning(f"Failed to parse JSON from {url}")
                            return None
                    elif resp.status == 401:
                        # Сессия истекла – пробуем перелогиниться и повторяем запрос
                        self._is_authenticated = False
                        if await self.login():
                            logger.info("Re-authenticated after 401, retrying request")
                            # Не увеличиваем attempt, чтобы не расходовать попытки
                            continue
                        else:
                            logger.error("Re-authentication failed after 401")
                            return None
                    else:
                        logger.warning(f"HTTP {resp.status} from {url}, attempt {attempt+1}/{self.MAX_RETRIES}")
            except asyncio.TimeoutError:
                logger.warning(f"Timeout on {url}, attempt {attempt+1}/{self.MAX_RETRIES}")
            except aiohttp.ClientError as e:
                logger.warning(f"Client error on {url}: {e}, attempt {attempt+1}/{self.MAX_RETRIES}")
            except Exception as e:
                logger.error(f"Unexpected error on {url}: {e}")

            attempt += 1
            if attempt < self.MAX_RETRIES:
                delay = self.RETRY_DELAY * (2 ** (attempt - 1))
                await asyncio.sleep(delay)

        logger.error(f"Failed to {method.upper()} {url} after {self.MAX_RETRIES} attempts")
        return None

    async def login(self) -> bool:
        if self._is_authenticated:
            return True
        if not self.base_url:
            logger.error("XUI_BASE_URL is not set")
            return False
        url = f"{self.base_url}/login"
        payload = {"username": self.username, "password": self.password}
        try:
            result = await self._retry_request("POST", url, data=payload)
            if result and result.get("success"):
                self._is_authenticated = True
                logger.info("Successfully authenticated with 3x-ui panel")
                return True
            else:
                logger.error(f"Authentication failed: {result.get('msg') if result else 'No response'}")
                return False
        except Exception as e:
            logger.error(f"Login exception: {e}")
            return False

    async def create_client(self, email: str) -> dict | None:
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
        except Exception as e:
            logger.error(f"Exception creating client: {e}")
            return None

    async def get_client_by_email(self, email: str) -> dict | None:
        if not await self.login():
            logger.error("Cannot search client: not authenticated")
            return None
        url = f"{self.base_url}/panel/api/inbounds/get/{self.inbound_id}"
        try:
            result = await self._retry_request("GET", url, headers=self.headers)
            if not result:
                return None
            inbound = result.get("obj")
            if not inbound:
                logger.error("Inbound not found in API response")
                return None
            settings_data = json.loads(inbound.get("settings", "{}"))
            for client in settings_data.get("clients", []):
                if client.get("email") == email:
                    return {
                        "uuid": client.get("id"),
                        "subId": client.get("subId", client.get("id")[:16])
                    }
            logger.debug(f"Client with email {email} not found")
            return None
        except Exception as e:
            logger.error(f"Exception searching client: {e}")
            return None

    def get_subscription_link(self, sub_id: str) -> str:
        if not self._server_address or not sub_id:
            logger.error("Invalid server address or sub_id")
            return ""
        return f"http://{self._server_address}:{self.sub_port}/sub/{sub_id}"

    async def revoke_client(self, client_uuid: str) -> bool:
        if not await self.login():
            logger.error("Cannot revoke client: not authenticated")
            return False
        del_endpoints = [
            f"{self.base_url}/panel/api/inbounds/{self.inbound_id}/delClient/{client_uuid}",
            f"{self.base_url}/panel/api/inbounds/delClient/{self.inbound_id}/Client/{client_uuid}",
        ]
        for url in del_endpoints:
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
    
# Глобальный экземпляр провайдера (использовать во всём проекте)
vpn_provider = XUIVPNProvider()