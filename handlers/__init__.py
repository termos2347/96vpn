from aiogram import Router
from .common import router as common_router
from .subscription import router as subscription_router
from .payment import router as payment_router
from .info import router as info_router
from .proxy import router as proxy_router

router = Router()
router.include_router(common_router)
router.include_router(subscription_router)
router.include_router(payment_router)
router.include_router(info_router)
router.include_router(proxy_router)