import logging
from aiogram import Router, types
from aiogram.filters import Command
from config import settings
from services.vpn_provider import XUIVPNProvider
from services.vpn_manager import VPNManager

logger = logging.getLogger(__name__)

# Глобальные переменные
_vpn_manager: VPNManager = None

def get_vpn_manager() -> VPNManager:
    return _vpn_manager

def set_vpn_manager(manager: VPNManager):
    global _vpn_manager
    _vpn_manager = manager

# Инициализация при старте (вызывается из run_all.py)
def init_vpn_components():
    global _vpn_manager
    if _vpn_manager is not None:
        return
    provider = XUIVPNProvider(
        base_url=settings.XUI_BASE_URL,
        username=settings.XUI_USERNAME,
        password=settings.XUI_PASSWORD,
        inbound_id=settings.XUI_INBOUND_ID,
        sub_port=settings.XUI_SUB_PORT
    )
    _vpn_manager = VPNManager(provider)
    logger.info("VPN components initialized with single 3x-UI panel")

# Роутер для основных команд – импортируем из других модулей
from .common import router as common_router
from .payment import router as payment_router

router = Router()
router.include_router(common_router)
router.include_router(payment_router)