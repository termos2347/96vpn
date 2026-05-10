from services.vpn_manager import VPNManager
from services.server_pool import ServerPool

# Глобальный экземпляр VPNManager (устанавливается в run_all.py)
_vpn_manager: VPNManager = None
# Глобальный пул серверов
_server_pool: ServerPool = None

def set_vpn_manager(manager: VPNManager) -> None:
    global _vpn_manager
    _vpn_manager = manager

def get_vpn_manager() -> VPNManager:
    if _vpn_manager is None:
        raise RuntimeError("VPNManager not initialized. Call set_vpn_manager() first.")
    return _vpn_manager

def set_server_pool(pool: ServerPool) -> None:
    global _server_pool
    _server_pool = pool

def get_server_pool() -> ServerPool:
    if _server_pool is None:
        raise RuntimeError("ServerPool not initialized. Call set_server_pool() first.")
    return _server_pool

# Импорты роутеров
from .common import router as common_router
from .subscription import router as subscription_router
from .payment import router as payment_router
from .proxy import router as proxy_router

router = common_router
router.include_router(subscription_router)
router.include_router(payment_router)
router.include_router(proxy_router)