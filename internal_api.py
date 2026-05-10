import logging
from datetime import datetime, timezone
from aiohttp import web
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from config import INTERNAL_API_SECRET
from db.crud import (
    set_vpn_subscription,
    set_bypass_subscription,
    get_or_create_bot_user,
    log_bot_payment,
)
from db.models import BotPayment
from db.base import AsyncSessionLocal
from services.vpn_manager import VPNManager
from admin import send_admin_alert
from handlers import get_vpn_manager

logger = logging.getLogger(__name__)
PERIOD_DAYS = {"1m": 30, "3m": 90, "6m": 180}


async def handle_activation(request):
    auth = request.headers.get("Authorization")
    if not auth or auth != f"Bearer {INTERNAL_API_SECRET}":
        return web.json_response({"error": "unauthorized"}, status=401)

    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400)

    required_fields = ["telegram_id", "product_type", "period"]
    if not all(k in data for k in required_fields):
        return web.json_response({"error": "missing fields"}, status=400)

    telegram_id = data["telegram_id"]
    product_type = data["product_type"]
    period = data["period"]
    payment_id = data.get("payment_id")

    if period not in PERIOD_DAYS:
        return web.json_response({"error": "invalid period"}, status=400)

    days = PERIOD_DAYS[period]

    # --- Основной путь: активация с payment_id (защита от дублей) ---
    if payment_id:
        async with AsyncSessionLocal() as session:
            # Проверяем, не обработан ли уже этот платёж
            result = await session.execute(
                select(BotPayment).where(BotPayment.payment_id == payment_id)
            )
            if result.scalars().first():
                logger.info(f"Payment {payment_id} already activated, skipping")
                return web.json_response({"status": "already_activated"})

            try:
                # Активируем подписку
                if product_type == "vpn":
                    await set_vpn_subscription(telegram_id, days)
                    # Используем глобальный менеджер VPN (с пулом серверов)
                    vpn_manager = get_vpn_manager()
                    try:
                        link = await vpn_manager.create_key(telegram_id, days)
                        if not link:
                            logger.error(f"Failed to create VPN key for {telegram_id}")
                            await send_admin_alert(
                                f"Не создался VPN-ключ (internal) для telegram_id={telegram_id}, payment_id={payment_id}"
                            )
                    except Exception as e:
                        logger.error(f"VPN key creation error: {e}")
                        await send_admin_alert(f"Ошибка создания ключа: {e}")
                elif product_type == "bypass":
                    await set_bypass_subscription(telegram_id, days)
                else:
                    return web.json_response({"error": "unknown product"}, status=400)

                # Идемпотентная вставка платежа (UPSERT)
                stmt = insert(BotPayment).values(payment_id=payment_id, telegram_id=telegram_id, created_at=datetime.now(timezone.utc))
                stmt = stmt.on_conflict_do_nothing(index_elements=['payment_id'])
                await session.execute(stmt)
                await session.commit()

                logger.info(f"Subscription activated for {telegram_id}, payment {payment_id}")
                return web.json_response({"status": "ok"})

            except Exception as e:
                await session.rollback()
                logger.error(f"Activation failed for {telegram_id}: {e}", exc_info=True)
                await send_admin_alert(
                    f"Ошибка активации подписки (internal) для telegram_id={telegram_id}, payment_id={payment_id}: {e}"
                )
                return web.json_response({"status": "error", "detail": str(e)}, status=500)

    # --- Старая логика (без payment_id) – сохраняем для совместимости ---
    try:
        if product_type == "vpn":
            await set_vpn_subscription(telegram_id, days)
            vpn_manager = get_vpn_manager()
            try:
                link = await vpn_manager.create_key(telegram_id, days)
                if not link:
                    logger.error(f"Failed to create VPN key for {telegram_id}")
                    await send_admin_alert(
                        f"Не создался VPN-ключ (internal, без payment_id) для telegram_id={telegram_id}"
                    )
            except Exception as e:
                logger.error(f"VPN key creation error: {e}")
        elif product_type == "bypass":
            await set_bypass_subscription(telegram_id, days)
        else:
            return web.json_response({"error": "unknown product"}, status=400)

        logger.info(f"Subscription activated (no payment_id): user={telegram_id}, type={product_type}, days={days}")
        return web.json_response({"status": "ok"})

    except Exception as e:
        logger.error(f"Activation failed: {e}", exc_info=True)
        await send_admin_alert(
            f"Ошибка активации (internal, без payment_id) для telegram_id={telegram_id}: {e}"
        )
        return web.json_response({"status": "error", "detail": str(e)}, status=500)


def create_internal_app():
    app = web.Application()
    app.router.add_post('/activate', handle_activation)
    return app