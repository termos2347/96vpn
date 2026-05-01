import logging
from aiohttp import web
from config import INTERNAL_API_SECRET
from db.crud import set_vpn_subscription, set_bypass_subscription
from services.vpn_manager import VPNManager
from services.dpi_bypass import enable_bypass  # заменишь реальной функцией позже

logger = logging.getLogger(__name__)

PERIOD_DAYS = {"1m": 30, "3m": 90, "6m": 180}


async def handle_activation(request):
    """Эндпоинт для активации подписки из веб-хука сайта."""
    # Проверка авторизации
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

    if period not in PERIOD_DAYS:
        return web.json_response({"error": "invalid period"}, status=400)

    days = PERIOD_DAYS[period]

    try:
        if product_type == "vpn":
            await set_vpn_subscription(telegram_id, days)
            # Создаём VPN-ключ
            manager = VPNManager()
            link = await manager.create_key(telegram_id, days)
            if not link:
                logger.error(f"Failed to create VPN key for {telegram_id}")
        elif product_type == "bypass":
            await set_bypass_subscription(telegram_id, days)
            # Здесь будет вызов активации обхода (заглушка)
            # await enable_bypass(telegram_id)
        else:
            return web.json_response({"error": "unknown product"}, status=400)

        logger.info(f"Subscription activated via internal API: user={telegram_id}, type={product_type}, days={days}")
        return web.json_response({"status": "ok"})

    except Exception as e:
        logger.error(f"Activation failed: {e}", exc_info=True)
        return web.json_response({"status": "error", "detail": str(e)}, status=500)


def create_internal_app():
    app = web.Application()
    app.router.add_post('/activate', handle_activation)
    return app