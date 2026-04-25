import os
import uuid
import json
import logging
import aiohttp
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

class XUIVPNProvider:
    def __init__(self):
        self.base_url = os.getenv("XUI_BASE_URL", "").rstrip('/')
        self.username = os.getenv("XUI_USERNAME")
        self.password = os.getenv("XUI_PASSWORD")
        self.inbound_id = int(os.getenv("XUI_INBOUND_ID", "1"))
        self.sub_port = int(os.getenv("XUI_SUB_PORT", "2096"))
        self.headers = {"Referer": f"{self.base_url}/panel/inbounds"}
        self.session: aiohttp.ClientSession | None = None
        self._server_address = self._extract_host(self.base_url)

    @staticmethod
    def _extract_host(url: str) -> str:
        if not url:
            return ""
        parts = url.split("://")[1].split("/")[0].split(":")[0]
        return parts

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            connector = aiohttp.TCPConnector(ssl=False, limit=100)
            self.session = aiohttp.ClientSession(
                connector=connector,
                cookie_jar=aiohttp.CookieJar(unsafe=True)
            )
        return self.session

    async def login(self) -> bool:
        session = await self._get_session()
        url = f"{self.base_url}/login"
        payload = {"username": self.username, "password": self.password}
        try:
            async with session.post(url, data=payload) as resp:
                data = await resp.json()
                return data.get("success", False)
        except Exception as e:
            logger.error(f"Ошибка входа в 3x-ui: {e}")
            return False

    async def create_client(self, email: str) -> dict | None:
        """Создаёт клиента, возвращает {'uuid': ..., 'subId': ...}"""
        if not await self.login():
            logger.error("Не удалось войти в панель 3x-ui")
            return None

        session = await self._get_session()
        client_uuid = str(uuid.uuid4())
        sub_id = str(uuid.uuid4()).replace('-', '')[:16]

        settings = {
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
                "flow": "xtls-rprx-vision"   # <-- добавить эту строку
            }]
        }
        payload = {
            "id": self.inbound_id,
            "settings": json.dumps(settings)
        }
        url = f"{self.base_url}/panel/api/inbounds/addClient"
        try:
            async with session.post(url, data=payload, headers=self.headers) as resp:
                data = await resp.json()
                if data.get("success"):
                    logger.info(f"Клиент {email} создан с UUID {client_uuid} и subId {sub_id}")
                    return {"uuid": client_uuid, "subId": sub_id}
                elif "Duplicate email" in data.get("msg", ""):
                    logger.warning(f"Email {email} уже существует")
                    return None
                else:
                    logger.error(f"Ошибка создания клиента: {data.get('msg')}")
                    return None
        except Exception as e:
            logger.error(f"Исключение при создании клиента: {e}")
            return None

    async def get_client_by_email(self, email: str) -> dict | None:
        """Ищет клиента по email, возвращает {'uuid': ..., 'subId': ...} или None"""
        if not await self.login():
            logger.error("Не удалось войти в панель для поиска клиента")
            return None
        session = await self._get_session()
        url = f"{self.base_url}/panel/api/inbounds/get/{self.inbound_id}"
        try:
            async with session.get(url, headers=self.headers) as resp:
                if resp.status != 200:
                    logger.error(f"Ошибка получения inbound при поиске клиента: {resp.status}")
                    return None
                data = await resp.json()
                inbound = data.get("obj")
                if not inbound:
                    logger.error("Inbound не найден в ответе API")
                    return None
                settings = json.loads(inbound.get("settings", "{}"))
                for client in settings.get("clients", []):
                    if client.get("email") == email:
                        sub_id = client.get("subId") or client.get("id")[:16]
                        logger.info(f"Найден клиент {email} с subId {sub_id}")
                        return {"uuid": client.get("id"), "subId": sub_id}
        except Exception as e:
            logger.error(f"Ошибка поиска клиента по email: {e}")
        return None

    def get_subscription_link(self, sub_id: str) -> str:
        """Возвращает ссылку подписки"""
        return f"http://{self._server_address}:{self.sub_port}/sub/{sub_id}"

    async def revoke_client(self, client_uuid: str) -> bool:
        """Безопасное удаление клиента по UUID через прямой эндпоинт (перебор вариантов)."""
        if not await self.login():
            return False

        session = await self._get_session()
        # Возможные пути для разных версий 3x-ui
        del_endpoints = [
            f"{self.base_url}/panel/api/inbounds/{self.inbound_id}/delClient/{client_uuid}",
            f"{self.base_url}/panel/api/inbounds/delClient/{self.inbound_id}/Client/{client_uuid}",
            f"{self.base_url}/api/inbounds/delClient/{self.inbound_id}/Client/{client_uuid}",
            f"{self.base_url}/panel/api/inbounds/delClient/{client_uuid}",
            f"{self.base_url}/panel/api/inbounds/{self.inbound_id}/delClient/{client_uuid}",
        ]

        for url in del_endpoints:
            try:
                async with session.post(url, headers=self.headers) as resp:
                    # Некоторые версии возвращают 200 с json, даже при ошибке
                    if resp.status == 200:
                        try:
                            data = await resp.json(content_type=None)
                            if data.get("success"):
                                logger.info(f"Клиент {client_uuid} удалён через {url}")
                                return True
                            else:
                                logger.debug(f"Попытка удаления по {url} вернула success=False: {data.get('msg')}")
                        except:
                            logger.debug(f"Ответ от {url} не содержит валидный JSON")
            except Exception as e:
                logger.debug(f"Ошибка при попытке удаления по {url}: {e}")
                continue

        logger.error(f"Не удалось удалить клиента {client_uuid} ни через один известный эндпоинт")
        return False

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()