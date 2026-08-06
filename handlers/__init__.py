# handlers/__init__.py
import logging
from aiogram import Router

from .common import router as common_router
from .payment import router as payment_router
from .ui import Keyboards

from services.vpn_provider import XUIVPNProvider
from services.vpn_manager import VPNManager, set_vpn_manager, get_vpn_manager
from config import settings

logger = logging.getLogger(__name__)

# Убираем автоматический вызов init_vpn_components()
# Теперь он вызывается явно в run_all.py

# Сборка основного роутера
router = Router()
router.include_router(common_router)
router.include_router(payment_router)

logger.info("✅ Main router assembled")