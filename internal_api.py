# internal_api.py
import asyncio
import ipaddress
import logging

from aiogram.exceptions import (
    TelegramAPIError,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)
from aiohttp import ClientError, web
from sqlalchemy import select
from sqlalchemy.exc import InterfaceError, OperationalError
from yookassa import Payment as YooPayment

from config import INTERNAL_API_SECRET, settings
from db.base import AsyncSessionLocal, retry_db_operation
from db.crud import activate_subscription, get_or_create_bot_user
from db.models import BotPayment
from services.payment_yookassa import YookassaTransientError, yookassa_service
from services.vpn_manager import get_vpn_manager

logger = logging.getLogger(__name__)

_DB_RETRYABLE = (OperationalError, InterfaceError)


def _is_trusted_proxy(ip: str) -> bool:
    """Проверяет, что ip входит в TRUSTED_PROXY_IPS (с поддержкой CIDR)."""
    if not ip:
        return False
    try:
        ip_obj = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for net in settings.TRUSTED_PROXY_IPS:
        try:
            net_obj = ipaddress.ip_network(net, strict=False)
        except ValueError:
            continue
        if ip_obj.version == net_obj.version and ip_obj in net_obj:
            return True
    return False


def get_client_ip(request: web.Request) -> str:
    """Возвращает IP клиента.

    X-Real-IP принимаем только если запрос пришёл с доверенного прокси —
    иначе любой внешний клиент мог бы подделать IP и обойти IP-фильтр ЮKassa.
    """
    remote = request.remote or ""
    real_ip = request.headers.get("X-Real-IP")
    remote_trusted = _is_trusted_proxy(remote)

    if real_ip and remote_trusted:
        return real_ip

    if real_ip and not remote_trusted:
        logger.warning(
            f"X-Real-IP={real_ip!r} ignored: remote {remote!r} is not in "
            f"TRUSTED_PROXY_IPS. Using remote IP. "
            f"Проверьте, что nginx переписывает X-Real-IP и добавлен в "
            f"TRUSTED_PROXY_IPS."
        )

    if not real_ip and remote_trusted:
        logger.warning(
            f"Request from trusted proxy {remote!r} has no X-Real-IP header. "
            f"Прокси должен выставлять X-Real-IP для корректной работы "
            f"IP-фильтра."
        )

    return remote


def ip_in_network(ip: str) -> bool:
    trusted = settings.YOOKASSA_TRUSTED_IPS
    try:
        ip_obj = ipaddress.ip_address(ip)
        for net in trusted:
            try:
                net_obj = ipaddress.ip_network(net, strict=False)
            except ValueError:
                logger.warning(f"Invalid CIDR in YOOKASSA_TRUSTED_IPS: {net!r}")
                continue
            if ip_obj.version != net_obj.version:
                continue
            if ip_obj in net_obj:
                return True
    except ValueError as e:
        logger.error(f"IP validation error: {e}")
    return False


def create_internal_app(main_bot, main_dp, admin_bot, admin_dp):
    app = web.Application()

    @retry_db_operation(max_retries=3)
    async def _activate_subscription_db(
        telegram_id: int,
        product_type: str,
        period: str,
        payment_id: str | None,
    ) -> str:
        """DB-часть активации. Возвращает:
        'ok' | 'already_activated' | 'failed'.

        Проверяем, что платёж принадлежит тому же telegram_id и что
        сумма соответствует цене за запрошенный period.
        """
        async with AsyncSessionLocal() as session, session.begin():
            user = await get_or_create_bot_user(
                session, telegram_id, for_update=True
            )

            if payment_id:
                stmt_payment = (
                    select(BotPayment)
                    .where(BotPayment.payment_id == payment_id)
                    .with_for_update()
                )
                db_payment = (
                    await session.execute(stmt_payment)
                ).scalar_one_or_none()

                if db_payment and db_payment.is_paid:
                    logger.info(
                        f"/activate: payment {payment_id} already processed"
                    )
                    return "already_activated"

                if db_payment:
                    if db_payment.telegram_id != telegram_id:
                        logger.error(
                            f"/activate: payment {payment_id} belongs to "
                            f"{db_payment.telegram_id}, not {telegram_id} — "
                            f"possible Bearer token leak / IDOR attempt"
                        )
                        return "failed"

                    expected_amount = settings.VPN_PRICES.get("rub", {}).get(
                        period
                    )
                    if expected_amount is None:
                        logger.error(
                            f"/activate: no expected amount for period "
                            f"{period!r}"
                        )
                        return "failed"
                    if abs(float(db_payment.amount) - expected_amount) > 0.01:
                        logger.error(
                            f"/activate: amount mismatch for {payment_id}: "
                            f"db={db_payment.amount}, "
                            f"expected={expected_amount} (period={period})"
                        )
                        return "failed"

            success = await activate_subscription(
                session,
                telegram_id,
                product_type,
                period,
                payment_id,
                user=user,
            )
            return "ok" if success else "failed"

    async def handle_activation(request):
        auth = request.headers.get("Authorization")
        if not auth or auth != f"Bearer {INTERNAL_API_SECRET}":
            return web.json_response({"error": "unauthorized"}, status=401)

        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json"}, status=400)

        required = ["telegram_id", "product_type", "period", "payment_id"]
        if not all(k in data for k in required):
            return web.json_response({"error": "missing fields"}, status=400)

        telegram_id = data["telegram_id"]
        product_type = data["product_type"]
        period = data["period"]
        payment_id = data["payment_id"]

        if not isinstance(telegram_id, int) or telegram_id <= 0:
            return web.json_response({"error": "invalid telegram_id"}, status=400)

        if not isinstance(payment_id, str) or not payment_id.strip():
            return web.json_response({"error": "invalid payment_id"}, status=400)

        if product_type != "vpn":
            return web.json_response(
                {"error": "unsupported product_type (only 'vpn')"}, status=400
            )

        if period not in settings.PERIOD_DAYS:
            return web.json_response({"error": "invalid period"}, status=400)

        # SECURITY BUGFIX: раньше /activate доверял локальной записи
        # BotPayment. Достаточно было создать pending-платёж (клик по
        # тарифу в боте) и вызвать /activate с утёкшим Bearer-токеном —
        # подписка активировалась БЕЗ оплаты. Теперь проверяем статус
        # платежа через YooKassa API (как в process_webhook).
        #
        # Выполняется до DB-транзакции — не держим FOR UPDATE во время
        # сетевого вызова.
        try:
            loop = asyncio.get_running_loop()
            verified = await asyncio.wait_for(
                loop.run_in_executor(
                    None, lambda: YooPayment.find_one(payment_id)
                ),
                timeout=15.0,
            )
        except Exception as e:
            logger.error(
                f"/activate: YooKassa API error for {payment_id}: {e}"
            )
            return web.json_response(
                {"error": "payment verification failed"}, status=503
            )

        if verified.status != "succeeded":
            logger.warning(
                f"/activate: payment {payment_id} not succeeded "
                f"(status={verified.status})"
            )
            return web.json_response(
                {"error": "payment not succeeded"}, status=400
            )

        if verified.amount is None or verified.amount.value is None:
            logger.error(
                f"/activate: payment {payment_id} returned no amount"
            )
            return web.json_response(
                {"error": "amount not available"}, status=400
            )

        expected_amount = settings.VPN_PRICES.get("rub", {}).get(period)
        if expected_amount is None or abs(
            float(verified.amount.value) - expected_amount
        ) > 0.01:
            logger.error(
                f"/activate: amount mismatch for {payment_id}: "
                f"api={verified.amount.value}, expected={expected_amount} "
                f"(period={period})"
            )
            return web.json_response({"error": "amount mismatch"}, status=400)

        try:
            result = await _activate_subscription_db(
                telegram_id, product_type, period, payment_id
            )
        except Exception:
            logger.exception("Activation DB error")
            return web.json_response({"status": "error"}, status=500)

        if result == "already_activated":
            return web.json_response(
                {"status": "already_activated"}, status=200
            )
        if result == "failed":
            logger.error(
                f"/activate: activate_subscription returned False for "
                f"telegram_id={telegram_id}, product={product_type}, "
                f"period={period}, payment_id={payment_id}"
            )
            return web.json_response({"error": "activation failed"}, status=400)

        # --- VPN-часть: best-effort, вне транзакции ---
        vpn_manager = get_vpn_manager()
        if vpn_manager:
            days = settings.PERIOD_DAYS[period]
            link: str | None = None
            try:
                link = await vpn_manager.create_vpn_key(telegram_id)
            except Exception as e:
                logger.exception(
                    f"/activate: VPN key creation failed for {telegram_id}: {e}"
                )
                from admin import send_admin_alert
                try:
                    await send_admin_alert(
                        f"/activate: не удалось создать ключ для "
                        f"{telegram_id}: {e}"
                    )
                except Exception:
                    logger.exception("Failed to send admin alert")
                link = None

            if link and main_bot:
                text = (
                    f"🔗 Ваша ссылка:\n{link}\n\n"
                    f"Подписка активна на {days} дней."
                )
                try:
                    await main_bot.send_message(telegram_id, text)
                except TelegramForbiddenError:
                    logger.info(
                        f"User {telegram_id} blocked bot, "
                        f"cannot send link from API"
                    )
                except TelegramRetryAfter as e:
                    logger.warning(
                        f"Flood limit for {telegram_id} (API), "
                        f"waiting {e.retry_after}s"
                    )
                    await asyncio.sleep(e.retry_after)
                    try:
                        await main_bot.send_message(telegram_id, text)
                    except TelegramAPIError as send_error:
                        logger.error(
                            f"Failed to send link to {telegram_id} "
                            f"after retry: {send_error}"
                        )
                except (TelegramNetworkError, ClientError) as e:
                    logger.warning(
                        f"Network error sending link to "
                        f"{telegram_id} from API: {e}"
                    )
                except Exception as e:
                    logger.error(
                        f"Unexpected error sending link to "
                        f"{telegram_id} from API: {e}"
                    )
        return web.json_response({"status": "ok"})

    async def yookassa_webhook(request):
        client_ip = get_client_ip(request)

        # BUGFIX: в DEBUG разрешаем loopback (localtunnel, локальные тесты).
        # Без этого документированный workflow из README не работает:
        # get_client_ip() возвращает 127.0.0.1, а ip_in_network() его режет
        # (в yookassa_ip.json loopback нет). В проде DEBUG=false — поведение
        # не меняется, loopback по-прежнему отклоняется.
        is_debug_loopback = bool(
            settings.DEBUG and client_ip in ("127.0.0.1", "::1")
        )
        if not is_debug_loopback and (
            not client_ip or not ip_in_network(client_ip)
        ):
            logger.warning(
                f"⛔ Blocked unauthorized webhook attempt from IP: {client_ip}"
            )
            return web.json_response({"error": "forbidden"}, status=403)
        if is_debug_loopback:
            logger.info(
                f"DEBUG: allowing loopback webhook from {client_ip} "
                f"(DEBUG=true — тестовый режим)"
            )

        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json"}, status=400)

        payment_id = data.get("object", {}).get("id")
        event = data.get("event")
        logger.info(f"🔔 Yookassa webhook {payment_id}: event={event}")

        if main_bot is None:
            logger.error("Main bot not set, cannot process yookassa webhook")
            return web.json_response(
                {"error": "main bot not ready"}, status=503
            )

        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                async with AsyncSessionLocal() as session, session.begin():
                    success = await yookassa_service.process_webhook(
                        data, session, main_bot
                    )

                if success:
                    logger.info("✅ Yookassa webhook processed successfully")
                    return web.json_response({"status": "ok"})
                else:
                    logger.warning("❌ Yookassa webhook processing failed")
                    return web.json_response({"status": "error"}, status=400)

            except _DB_RETRYABLE as e:
                logger.warning(
                    f"⏳ Yookassa webhook {payment_id} DB transient error "
                    f"(attempt {attempt}/{max_attempts}): {e}"
                )
                if attempt == max_attempts:
                    return web.json_response({"status": "retry"}, status=500)
                await asyncio.sleep(1.0 * (2 ** (attempt - 1)))

            except YookassaTransientError as e:
                logger.warning(
                    f"⏳ Yookassa webhook {payment_id} transient error, "
                    f"YooKassa will retry: {e}"
                )
                return web.json_response({"status": "retry"}, status=500)

            except Exception:
                logger.exception("❌ Yookassa webhook error")
                return web.json_response({"status": "error"}, status=500)

        return web.json_response({"status": "retry"}, status=500)

    async def telegram_webhook(request):
        if main_bot is None or main_dp is None:
            logger.warning("Main bot or dispatcher is None, returning 503")
            return web.json_response({"error": "main bot not ready"}, status=503)

        if settings.WEBHOOK_SECRET:
            secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
            if secret != settings.WEBHOOK_SECRET:
                return web.json_response({"error": "invalid secret"}, status=403)

        try:
            from aiogram.types import Update

            data = await request.json()
            update = Update(**data)
            await main_dp.feed_update(main_bot, update)
            return web.json_response({"status": "ok"})
        except Exception:
            logger.exception("Main bot webhook error")
            return web.json_response({"status": "error"}, status=500)

    async def admin_telegram_webhook(request):
        if admin_bot is None or admin_dp is None:
            logger.warning("Admin bot or dispatcher is None, returning 503")
            return web.json_response({"error": "admin bot not ready"}, status=503)

        if settings.ADMIN_WEBHOOK_SECRET:
            secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
            if secret != settings.ADMIN_WEBHOOK_SECRET:
                return web.json_response({"error": "invalid secret"}, status=403)

        try:
            from aiogram.types import Update

            data = await request.json()
            update = Update(**data)
            await admin_dp.feed_update(admin_bot, update)
            return web.json_response({"status": "ok"})
        except Exception:
            logger.exception("Admin bot webhook error")
            return web.json_response({"status": "error"}, status=500)

    app.router.add_post("/activate", handle_activation)
    app.router.add_post("/yookassa_webhook", yookassa_webhook)
    app.router.add_post("/webhook", telegram_webhook)
    app.router.add_post("/webhook/admin", admin_telegram_webhook)

    return app