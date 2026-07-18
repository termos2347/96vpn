# handlers/__init__.py
import logging
from aiogram import Router

from .common import router as common_router
from .payment import router as payment_router

# Импортируем функции для инициализации VPN-компонентов (они остаются без изменений)
from services.vpn_provider import XUIVPNProvider
from services.vpn_manager import VPNManager, set_vpn_manager, get_vpn_manager
from config import settings

logger = logging.getLogger(__name__)

def init_vpn_components():
    """Инициализирует VPN-компоненты при старте бота."""
    if get_vpn_manager() is not None:
        logger.info("VPN components already initialized, skipping.")
        return

    provider = XUIVPNProvider(
        base_url=settings.XUI_MASTER_URL,
        api_token=settings.XUI_API_TOKEN,
        inbound_id=settings.XUI_INBOUND_ID,
        sub_port=settings.XUI_SUB_PORT
    )
    manager = VPNManager(provider)
    set_vpn_manager(manager)
    logger.info("VPN components initialized with single 3x-UI panel (Master)")

# Сборка основного роутера
router = Router()
router.include_router(common_router)
router.include_router(payment_router)

__all__ = [
    "router",
    "init_vpn_components",
    "set_vpn_manager",
    "get_vpn_manager",
]