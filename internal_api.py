import logging
from datetime import datetime, timezone
from aiohttp import web
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from config import INTERNAL_API_SECRET, settings
from db.crud import (
    activate_subscription,
    update_vpn_subscription,
    update_bypass_subscription,
)
from db.models import BotPayment
from db.base import AsyncSessionLocal
from handlers import get_vpn_manager
from services.payment_yookassa import yookassa_service
from admin import send_admin_alert

logger = logging.getLogger(__name__)
PERIOD_DAYS = {"1m": 30, "3m": 90, "6m": 180}

# ------------------------------------------------------------------
# Глобальные переменные для вебхуков (устанавливаются из run_all.py)
# ------------------------------------------------------------------
_main_bot = None
_main_dp = None
_admin_bot = None
_admin_dp = None

def set_main_bot(bot):
    global _main_bot
    _main_bot = bot

def set_main_dp(dp):
    global _main_dp
    _main_dp = dp

def set_admin_bot(bot):
    global _admin_bot
    _admin_bot = bot

def set_admin_dp(dp):
    global _admin_dp
    _admin_dp = dp

# ------------------------------------------------------------------
# Внутренний эндпоинт для активации подписки (бот -> сайт)
# ------------------------------------------------------------------
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
            # После коммита создаём VPN-ключ (если нужно)
            if product_type == "vpn":
                vpn_manager = get_vpn_manager()
                if vpn_manager:
                    days = PERIOD_DAYS[period]
                    link = await vpn_manager.create_key(telegram_id, days)
                    if link and _main_bot:
                        try:
                            await _main_bot.send_message(
                                telegram_id,
                                f"🔗 Ваша VPN ссылка: {link}\n\nПодписка активирована на {days} дней."
                            )
                        except Exception as e:
                            logger.error(f"Failed to send link to user {telegram_id}: {e}")
            return web.json_response({"status": "ok"})
        else:
            return web.json_response({"status": "already_activated"}, status=200)
    except Exception as e:
        logger.error(f"Activation error: {e}", exc_info=True)
        return web.json_response({"status": "error"}, status=500)

# ------------------------------------------------------------------
# Вебхук ЮKassa
# ------------------------------------------------------------------
async def yookassa_webhook(request):
    try:
        data = await request.json()
        async with AsyncSessionLocal() as session:
            success = await yookassa_service.process_webhook(data, session, _main_bot)
        if success:
            return web.json_response({"status": "ok"})
        else:
            return web.json_response({"status": "error"}, status=500)
    except Exception as e:
        logger.error(f"Yookassa webhook error: {e}", exc_info=True)
        return web.json_response({"status": "error"}, status=500)

# ------------------------------------------------------------------
# Вебхук основного Telegram бота
# ------------------------------------------------------------------
async def telegram_webhook(request):
    if _main_bot is None or _main_dp is None:
        return web.json_response({"error": "main bot not ready"}, status=503)

    # Проверка секретного токена
    if settings.WEBHOOK_SECRET:
        secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if secret != settings.WEBHOOK_SECRET:
            return web.json_response({"error": "invalid secret"}, status=403)

    try:
        from aiogram.types import Update
        data = await request.json()
        update = Update(**data)
        await _main_dp.feed_update(_main_bot, update)
        return web.json_response({"status": "ok"})
    except Exception as e:
        logger.error(f"Main bot webhook error: {e}", exc_info=True)
        return web.json_response({"status": "error"}, status=500)

# ------------------------------------------------------------------
# Вебхук административного Telegram бота
# ------------------------------------------------------------------
async def admin_telegram_webhook(request):
    if _admin_bot is None or _admin_dp is None:
        return web.json_response({"error": "admin bot not ready"}, status=503)

    if settings.ADMIN_WEBHOOK_SECRET:
        secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if secret != settings.ADMIN_WEBHOOK_SECRET:
            return web.json_response({"error": "invalid secret"}, status=403)

    try:
        from aiogram.types import Update
        data = await request.json()
        update = Update(**data)
        await _admin_dp.feed_update(_admin_bot, update)
        return web.json_response({"status": "ok"})
    except Exception as e:
        logger.error(f"Admin bot webhook error: {e}", exc_info=True)
        return web.json_response({"status": "error"}, status=500)

# ------------------------------------------------------------------
# Создание aiohttp приложения
# ------------------------------------------------------------------
def create_internal_app():
    app = web.Application()
    app.router.add_post('/activate', handle_activation)
    app.router.add_post('/yookassa_webhook', yookassa_webhook)
    app.router.add_post('/api/payment/webhook/yookassa', yookassa_webhook)
    app.router.add_post('/webhook', telegram_webhook)
    app.router.add_post('/webhook/admin', admin_telegram_webhook)
    return app