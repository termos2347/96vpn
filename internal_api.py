import logging
from datetime import datetime, timezone
from aiohttp import web
from config import INTERNAL_API_SECRET
from db.crud import set_vpn_subscription, set_bypass_subscription
from db.models import PaymentLog
from db.base import AsyncSessionLocal
from services.vpn_manager import VPNManager
from sqlalchemy import select

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

    # --- Если передан payment_id, проверяем, не обработан ли он уже ---
    if payment_id:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(PaymentLog).where(PaymentLog.payment_id == payment_id)
            )
            if result.scalars().first():
                logger.info(f"Payment {payment_id} already activated, skipping")
                return web.json_response({"status": "already_activated"})

            # Платеж новый – активируем подписку
            try:
                if product_type == "vpn":
                    await set_vpn_subscription(telegram_id, days)
                    manager = VPNManager()
                    try:
                        link = await manager.create_key(telegram_id, days)
                        if not link:
                            logger.error(f"Failed to create VPN key for {telegram_id}")
                    finally:
                        await manager.close()
                elif product_type == "bypass":
                    await set_bypass_subscription(telegram_id, days)
                else:
                    return web.json_response({"error": "unknown product"}, status=400)

                # Только после успешной активации фиксируем payment_id
                session.add(PaymentLog(
                    payment_id=payment_id,
                    telegram_id=telegram_id,
                    created_at=datetime.now(timezone.utc)
                ))
                await session.commit()
                logger.info(f"Subscription activated for {telegram_id}, payment {payment_id}")
                return web.json_response({"status": "ok"})

            except Exception as e:
                await session.rollback()
                logger.error(f"Activation failed for {telegram_id}: {e}", exc_info=True)
                return web.json_response({"status": "error", "detail": str(e)}, status=500)

    # --- Без payment_id – старая логика (без защиты от дублей) ---
    try:
        if product_type == "vpn":
            await set_vpn_subscription(telegram_id, days)
            manager = VPNManager()
            try:
                link = await manager.create_key(telegram_id, days)
                if not link:
                    logger.error(f"Failed to create VPN key for {telegram_id}")
            finally:
                await manager.close()
        elif product_type == "bypass":
            await set_bypass_subscription(telegram_id, days)
        else:
            return web.json_response({"error": "unknown product"}, status=400)

        logger.info(f"Subscription activated (no payment_id): user={telegram_id}, type={product_type}, days={days}")
        return web.json_response({"status": "ok"})

    except Exception as e:
        logger.error(f"Activation failed: {e}", exc_info=True)
        return web.json_response({"status": "error", "detail": str(e)}, status=500)


def create_internal_app():
    app = web.Application()
    app.router.add_post('/activate', handle_activation)
    return app