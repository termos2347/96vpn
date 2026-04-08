# Заглушка для управления VPN-ключами
class VPNManager:
    async def create_key(self, user_id: int, server_id: int) -> str:
        return "vless://fake-config"
    async def revoke_key(self, key_id: str):
        pass