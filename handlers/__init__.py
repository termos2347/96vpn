# handlers/__init__.py
import logging
from aiogram import Router
from aiogram.types import CallbackQuery

from .common import router as common_router
from .payment import router as payment_router
from .ui import Keyboards

from services.vpn_provider import XUIVPNProvider
from services.vpn_manager import VPNManager, set_vpn_manager, get_vpn_manager
from config import settings

logger = logging.getLogger(__name__)

def init_vpn_components():
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

# Fallback-обработчик для неизвестных callback-запросов
@router.callback_query()
async def unknown_callback(callback: CallbackQuery):
    await callback.answer("❌ Неизвестная команда", show_alert=False)
    try:
        await callback.message.edit_text(
            "❌ Кнопка устарела или была нажата ошибочно.\nНажмите /start для главного меню.",
            reply_markup=Keyboards.back_to_main_inline()
        )
    except Exception:
        # Если сообщение уже удалено или не редактируется, просто игнорируем
        pass

__all__ = [
    "router",
    "init_vpn_components",
    "set_vpn_manager",
    "get_vpn_manager",
]