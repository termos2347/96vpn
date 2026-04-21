import asyncio
import logging
from datetime import datetime
from db.base import AsyncSessionLocal
from db.models import User
from db.crud import set_vpn_client_id
from services.vpn_provider import XUIVPNProvider
from sqlalchemy import select

logger = logging.getLogger(__name__)
vpn_provider = XUIVPNProvider()

async def check_expired_subscriptions(bot):
    """Проверяет истёкшие подписки и отзывает ключи."""
    while True:
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(User).where(
                        User.vpn_subscription_end < datetime.now(),
                        User.vpn_client_id.isnot(None)
                    )
                )
                expired_users = result.scalars().all()
                
                for user in expired_users:
                    client_uuid = user.vpn_client_id
                    success = await vpn_provider.revoke_client(client_uuid)
                    if success:
                        user.vpn_client_id = None
                        await session.commit()
                        logger.info(f"Ключ {client_uuid} отозван для user_id={user.user_id}")
                        try:
                            await bot.send_message(
                                user.user_id,
                                "❌ Ваша VPN-подписка истекла. Для продления перейдите в раздел оплаты."
                            )
                        except Exception as e:
                            logger.error(f"Не удалось отправить уведомление пользователю {user.user_id}: {e}")
                    else:
                        logger.error(f"Не удалось отозвать ключ {client_uuid} для user_id={user.user_id}")
        except Exception as e:
            logger.error(f"Ошибка в фоновой задаче проверки подписок: {e}", exc_info=True)
        
        await asyncio.sleep(3600)  # Проверяем раз в час

async def start_scheduler(bot):
    """Запускает фоновую задачу."""
    asyncio.create_task(check_expired_subscriptions(bot))
    logger.info("Фоновая проверка подписок запущена")