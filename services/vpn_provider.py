import os
import json
import uuid
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
        self.headers = {"Referer": f"{self.base_url}/panel/inbounds"}
        self.session: aiohttp.ClientSession | None = None
        self._server_address = self._extract_host(self.base_url)

    @staticmethod
    def _extract_host(url: str) -> str:
        # Из https://185.5.75.235:53983/... получаем 185.5.75.235
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
            async with session.post(url, data=payload, headers={"Referer": f"{self.base_url}/"}) as resp:
                data = await resp.json()
                return data.get("success", False)
        except Exception as e:
            logger.error(f"Ошибка входа в 3x-ui: {e}")
            return False

    async def create_client(self, email: str) -> str | None:
        """Создаёт клиента, возвращает UUID или None"""
        if not await self.login():
            logger.error("Не удалось войти в панель 3x-ui")
            return None

        session = await self._get_session()
        client_uuid = str(uuid.uuid4())
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
                "subId": ""
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
                    logger.info(f"Клиент {email} создан с UUID {client_uuid}")
                    return client_uuid
                elif "Duplicate email" in data.get("msg", ""):
                    logger.warning(f"Email {email} уже существует")
                    # Можно попытаться найти существующий UUID и вернуть его
                    return await self._get_existing_client_uuid(email)
                else:
                    logger.error(f"Ошибка создания клиента: {data.get('msg')}")
                    return None
        except Exception as e:
            logger.error(f"Исключение при создании клиента: {e}")
            return None

    async def _get_existing_client_uuid(self, email: str) -> str | None:
        """Ищет UUID клиента по email в текущем inbound"""
        session = await self._get_session()
        url = f"{self.base_url}/panel/api/inbounds/get/{self.inbound_id}"
        try:
            async with session.post(url) as resp:
                data = await resp.json()
                inbound = data.get("obj", {})
                if inbound:
                    settings = json.loads(inbound.get("settings", "{}"))
                    for client in settings.get("clients", []):
                        if client.get("email") == email:
                            return client.get("id")
        except Exception as e:
            logger.error(f"Ошибка поиска существующего клиента: {e}")
        return None

    async def revoke_client(self, client_uuid: str) -> bool:
        """Удаляет клиента по UUID"""
        if not await self.login():
            return False
        session = await self._get_session()
        # Получаем текущие настройки
        url_get = f"{self.base_url}/panel/api/inbounds/get/{self.inbound_id}"
        try:
            async with session.post(url_get) as resp:
                data = await resp.json()
                inbound = data.get("obj", {})
                if not inbound:
                    return False
                settings = json.loads(inbound.get("settings", "{}"))
                clients = settings.get("clients", [])
                new_clients = [c for c in clients if c.get("id") != client_uuid]
                if len(new_clients) == len(clients):
                    return False  # клиент не найден
                settings["clients"] = new_clients
                payload = {
                    "id": self.inbound_id,
                    "settings": json.dumps(settings)
                }
                url_update = f"{self.base_url}/panel/api/inbounds/update/{self.inbound_id}"
                async with session.post(url_update, data=payload) as resp_update:
                    result = await resp_update.json()
                    return result.get("success", False)
        except Exception as e:
            logger.error(f"Ошибка удаления клиента: {e}")
            return False

    async def get_client_config(self, client_uuid: str) -> str | None:
        """Генерирует VLESS-ссылку на основе параметров inbound из .env."""
        # Загружаем параметры из окружения с fallback-значениями
        port = int(os.getenv("XUI_INBOUND_PORT", "443"))
        network = os.getenv("XUI_INBOUND_NETWORK", "tcp")
        security = os.getenv("XUI_INBOUND_SECURITY", "reality")
        public_key = os.getenv("XUI_REALITY_PUBLIC_KEY", "")
        short_id = os.getenv("XUI_REALITY_SHORT_ID", "")
        server_name = os.getenv("XUI_REALITY_SERVER_NAME", "")
        flow = os.getenv("XUI_FLOW", "xtls-rprx-vision")

        # Проверяем обязательные параметры
        if not all([public_key, short_id, server_name]):
            logger.error("Отсутствуют параметры Reality в .env. Конфиг не может быть сгенерирован.")
            return None

        # IP сервера извлекается из BASE_URL
        remark = f"96VPN-{client_uuid[:8]}"
        config = (
            f"vless://{client_uuid}@{self._server_address}:{port}"
            f"?type={network}&security={security}"
            f"&pbk={public_key}&sid={short_id}&sni={server_name}"
            f"&flow={flow}#{remark}"
        )
        logger.info(f"Сгенерирован конфиг для клиента {client_uuid}")
        return config

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()