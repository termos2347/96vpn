import asyncio
import logging
import ssl
import uuid
from typing import Any
from urllib.parse import urlsplit

import aiohttp

from config import settings

logger = logging.getLogger(__name__)


class _NotFoundType(dict):
    """Sentinel: «панель ответила 404». Отличаем от ошибки (None).

    Подкласс dict — чтобы .get() на нём был валиден для статических
    анализаторов (Pylance). Реально .get() на нём никогда не вызывается:
    все места после получения результата сначала делают `is _NOT_FOUND`.
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return "<NOT_FOUND>"


_NOT_FOUND = _NotFoundType()


def _email_to_tg_id(email: str) -> int:
    """Детерминированный tgId для email.

    BUGFIX: раньше использовался `hash(email) % 1000000`, но `hash()`
    в Python рандомизируется per-process (PYTHONHASHSEED) — tgId для
    одного и того же email менялся между перезапусками бота. Для
    ветки `tg_...` это неважно (user_id парсится из email), но для
    остальных — ломало стабильность на панели.

    Используем UUIDv5 (namespace URL) — детерминированный и без
    дополнительных зависимостей.
    """
    return uuid.uuid5(uuid.NAMESPACE_URL, email).int % 1_000_000


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
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        self._session: aiohttp.ClientSession | None = None
        self._session_lock = asyncio.Lock()
        self._session_invalid = False
        self._closed = False

        self._server_host = self._extract_host(self.base_url)

    @staticmethod
    def _extract_host(url: str) -> str:
        """BUGFIX: urlsplit корректно обрабатывает IPv6 ([::1]).

        Раньше `url.split('://')[1].split('/')[0].split(':')[0]` на IPv6
        возвращал мусор и subscription-link получался вида https://[:...
        """
        try:
            return urlsplit(url).hostname or ""
        except Exception as e:
            logger.error(f"Failed to extract host from URL: {url}: {e}")
            return ""

    def _ssl_context(self) -> bool | ssl.SSLContext:
        """Возвращает SSL-настройки для TCPConnector.

        True  — использовать дефолтный контекст с проверкой сертификата.
        SSLContext — кастомный контекст (при VERIFY_SSL=false — без проверки).
        """
        if not settings.VERIFY_SSL:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            return ctx
        return True

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._closed:
            raise RuntimeError("Provider is closed")
        async with self._session_lock:
            if self._closed:
                raise RuntimeError("Provider is closed")
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
    ) -> dict[str, Any] | _NotFoundType | None:
        attempt = 0
        while attempt < self.MAX_RETRIES:
            try:
                if self._closed:
                    logger.warning(f"Provider closed, skip {method.upper()} {url}")
                    return None
                session = await self._get_session()
                # BUGFIX: не мутируем kwargs вызывающего кода.
                call_kwargs = dict(kwargs)
                call_headers = dict(call_kwargs.get("headers") or {})
                call_headers["Authorization"] = f"Bearer {self.api_token}"
                call_kwargs["headers"] = call_headers

                method_func = getattr(session, method.lower())
                async with method_func(url, **call_kwargs) as resp:
                    if resp.status == 200:
                        try:
                            return await resp.json()
                        except Exception:
                            return None
                    elif resp.status == 401:
                        logger.error("API token invalid or expired")
                        return None
                    elif resp.status == 404:
                        logger.info(f"HTTP 404 from {url} (not found)")
                        return _NOT_FOUND
                    elif resp.status == 429:
                        logger.warning(
                            f"HTTP 429 from {url} (rate limited), "
                            f"attempt {attempt + 1}/{self.MAX_RETRIES}"
                        )
                    elif resp.status >= 500:
                        logger.warning(
                            f"HTTP {resp.status} from {url} (server error), "
                            f"attempt {attempt + 1}/{self.MAX_RETRIES}"
                        )
                    else:
                        logger.warning(
                            f"HTTP {resp.status} from {url} "
                            f"(client error, no retry)"
                        )
                        return None
            except (TimeoutError, aiohttp.ClientError) as net_err:
                logger.warning(
                    f"Network error on {url} (attempt {attempt + 1}): "
                    f"{type(net_err).__name__}"
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
        if email.startswith("tg_"):
            try:
                parts = email.split("_")
                user_id = int(parts[1])
            except Exception:
                logger.warning(f"Could not parse user_id from email {email}")
                user_id = _email_to_tg_id(email)
        else:
            user_id = _email_to_tg_id(email)

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
            if result is _NOT_FOUND:
                logger.error(f"Panel returned 404 for {url}")
                return None
            if result and result.get("success") is True:
                logger.info(f"Client {email} created successfully with subId={sub_id}")
                return {"uuid": client_uuid, "subId": sub_id}
            logger.error(f"Failed to create client: {result}")
            return None
        except Exception:
            logger.exception("Exception creating client")
            return None

    async def get_client_by_email(self, email: str) -> dict[str, str] | None:
        """Ищет клиента по email. Пытается извлечь subId из разных полей ответа."""
        url = f"{self.base_url}/panel/api/clients/get/{email}"
        try:
            result = await self._retry_request("GET", url)
            if result is _NOT_FOUND:
                logger.debug(f"get_client_by_email: {email} not found (404)")
                return None
            if not result or result.get("success") is not True:
                logger.info(
                    f"get_client_by_email {email}: panel returned "
                    f"{str(result)[:200]!r}"
                )
                return None

            data = result.get("obj")
            if data:
                sub_id = (
                    data.get("subId") or data.get("subid") or data.get("sub_id")
                )
                client_uuid = data.get("id") or data.get("uuid")
                client_email = data.get("email")
                enable = data.get("enable")

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
                logger.warning(f"Client found but no subId in response: {data}")
                return None
            return None
        except Exception:
            logger.exception(f"Error getting client by email {email}")
            return None

    async def get_client_by_sub_id(self, sub_id: str) -> dict[str, str] | None:
        """Пытается найти клиента по subId через эндпоинт /getSub/{subId}.

        Выполняет только одну попытку (без ретраев), так как эндпоинт
        часто недоступен и отдаёт HTML.
        """
        if not sub_id:
            return None

        if len(sub_id) > 16:
            original = sub_id
            sub_id = sub_id[:16]
            logger.debug(f"Trimmed subId from '{original}' to '{sub_id}'")

        url = f"{self.base_url}/panel/api/clients/getSub/{sub_id}"
        # BUGFIX: раньше использовался self.headers без Authorization —
        # эндпоинт всегда возвращал 401, и метод был мёртвым (спасал
        # только fallback через get_all_clients). Добавляем Bearer.
        headers = {**self.headers, "Authorization": f"Bearer {self.api_token}"}
        try:
            session = await self._get_session()
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    try:
                        result = await resp.json()
                    except Exception as e:
                        logger.warning(
                            f"get_client_by_sub_id: {sub_id} — 200 but "
                            f"non-JSON (content-type={resp.content_type!r}): {e}"
                        )
                        return None

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
                elif resp.status == 404:
                    logger.debug(f"Client with subId {sub_id} not found (404)")
                elif resp.status == 401:
                    logger.error(
                        f"get_client_by_sub_id: 401 for subId {sub_id} — "
                        f"token invalid or endpoint protected differently"
                    )
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
            if result is _NOT_FOUND:
                return []
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
        host = self._server_host
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        return f"https://{host}:{self.sub_port}/sub/{sub_id}"

    async def revoke_client(self, sub_id: str) -> bool | None:
        """Удаляет клиента по subId.

        Возвращает:
            True  — удалён (панель вернула success=true);
            None  — клиент не найден на панели (404) — считаем отозванным;
            False — ошибка (auth/network/5xx) — НЕ считаем отозванным.
        """
        if not sub_id:
            logger.error("revoke_client: empty sub_id")
            return False

        sub_id = sub_id[:16]
        url = f"{self.base_url}/panel/api/clients/delSub/{sub_id}"
        try:
            result = await self._retry_request("POST", url)
            if result is _NOT_FOUND:
                logger.info(f"Client with subId {sub_id} not found (404)")
                return None
            if result and result.get("success") is True:
                logger.info(f"Client with subId {sub_id} revoked")
                return True
            logger.warning(f"Failed to revoke by subId, result: {result}")
            return False
        except Exception:
            logger.exception(f"Error revoking client by subId {sub_id}")
            return False
