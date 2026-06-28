import logging
from datetime import datetime, timezone
from aiohttp import web
from sqlalchemy import select

from config import INTERNAL_API_SECRET, settings
from db.crud import activate_subscription
from db.base import AsyncSessionLocal, retry_db_operation
from handlers import get_vpn_manager
from services.payment_yookassa import yookassa_service

logger = logging.getLogger(__name__)


def ip_in_network(ip: str) -> bool:
    """Проверяет, входит ли IP-адрес в одну из доверенных сетей ЮKassa (из настроек)."""
    import ipaddress
    trusted = settings.YOOKASSA_TRUSTED_IPS
    try:
        ip_obj = ipaddress.ip_address(ip)
        for net in trusted:
            if "/" in net:
                if ip_obj in ipaddress.ip_network(net):
                    return True
            else:
                if ip_obj == ipaddress.ip_address(net):
                    return True
    except Exception as e:
        logger.error(f"IP validation error: {e}")
    return False


def create_internal_app(main_bot, main_dp, admin_bot, admin_dp):
    """
    Создаёт aiohttp приложение с эндпоинтами, используя переданные объекты ботов и диспетчеров.
    """
    app = web.Application()

    # ---------- Обработчик /activate ----------
    @retry_db_operation(max_retries=3)
    async def handle_activation(request):
        auth = request.headers.get("Authorization")
        if not auth or auth != f"Bearer {INTERNAL_API_SECRET}":
            return web.json_response({"error": "unauthorized"}, status=401)

        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json"}, status=400)

        required = ["telegram_id", "product_type", "period"]
        if not all(k in data for k in required):
            return web.json_response({"error": "missing fields"}, status=400)

        telegram_id = data["telegram_id"]
        product_type = data["product_type"]
        period = data["period"]
        payment_id = data.get("payment_id")

        try:
            async with AsyncSessionLocal() as session:
                async with session.begin():
                    success = await activate_subscription(
                        session, telegram_id, product_type, period, payment_id
                    )
            if success:
                if product_type == "vpn":
                    vpn_manager = get_vpn_manager()
                    if vpn_manager:
                        days = settings.PERIOD_DAYS[period]
                        link = await vpn_manager.create_key(telegram_id, days)
                        if link and main_bot:
                            try:
                                await main_bot.send_message(
                                    telegram_id,
                                    f"🔗 Ваша VPN ссылка: {link}\n\nПодписка активирована на {days} дней."
                                )
                            except Exception as e:
                                logger.error(f"Failed to send link to user {telegram_id}: {e}")
                return web.json_response({"status": "ok"})
            return web.json_response({"status": "already_activated"}, status=200)
        except Exception as e:
            logger.error(f"Activation error: {e}", exc_info=True)
            return web.json_response({"status": "error"}, status=500)

    # ---------- Обработчик вебхука ЮKassa ----------
    async def yookassa_webhook(request):
        forwarded_for = request.headers.get("X-Forwarded-For")
        client_ip = forwarded_for.split(",")[0].strip() if forwarded_for else request.remote

        if not client_ip or not ip_in_network(client_ip):
            logger.warning(f"Blocked unauthorized webhook attempt from IP: {client_ip}")
            return web.json_response({"error": "forbidden"}, status=403)

        try:
            data = await request.json()
            if main_bot is None:
                logger.error("Main bot not set, cannot process yookassa webhook")
                return web.json_response({"error": "main bot not ready"}, status=503)

            async with AsyncSessionLocal() as session:
                success = await yookassa_service.process_webhook(data, session, main_bot)

            if success:
                return web.json_response({"status": "ok"})
            return web.json_response({"status": "error"}, status=400)
        except Exception as e:
            logger.error(f"Yookassa webhook error: {e}", exc_info=True)
            return web.json_response({"status": "error"}, status=500)

    # ---------- Обработчик вебхука основного бота ----------
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
        except Exception as e:
            logger.error(f"Main bot webhook error: {e}", exc_info=True)
            return web.json_response({"status": "error"}, status=500)

    # ---------- Обработчик вебхука админ-бота ----------
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
        except Exception as e:
            logger.error(f"Admin bot webhook error: {e}", exc_info=True)
            return web.json_response({"status": "error"}, status=500)

    # ---------- Регистрация маршрутов ----------
    app.router.add_post('/activate', handle_activation)
    app.router.add_post('/yookassa_webhook', yookassa_webhook)
    app.router.add_post('/api/payment/webhook/yookassa', yookassa_webhook)
    app.router.add_post('/webhook', telegram_webhook)
    app.router.add_post('/webhook/admin', admin_telegram_webhook)

    return app