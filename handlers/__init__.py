# handlers/__init__.py
from aiogram import Router

from .common import router as common_router
from .payment import router as payment_router

router = Router()
router.include_router(common_router)
router.include_router(payment_router)