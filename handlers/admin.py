from aiogram import Router, F, types
from aiogram.filters import Command
from db.crud import set_vpn_subscription, get_vpn_client_id, set_vpn_client_id
from services.vpn_provider import XUIVPNProvider
from config import ADMIN_IDS

router = Router()
vpn_provider = XUIVPNProvider()

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

@router.message(Command("add_sub"))
async def add_subscription(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    args = message.text.split()
    if len(args) != 3:
        await message.answer("Использование: /add_sub <user_id> <days>")
        return
    try:
        user_id = int(args[1])
        days = int(args[2])
    except ValueError:
        await message.answer("user_id и days должны быть числами")
        return
    await set_vpn_subscription(user_id, days)
    await message.answer(f"✅ Подписка пользователя {user_id} продлена на {days} дней")

@router.message(Command("revoke"))
async def revoke_key(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    args = message.text.split()
    if len(args) != 2:
        await message.answer("Использование: /revoke <user_id>")
        return
    try:
        user_id = int(args[1])
    except ValueError:
        await message.answer("user_id должен быть числом")
        return
    client_uuid = await get_vpn_client_id(user_id)
    if not client_uuid:
        await message.answer("У пользователя нет активного ключа")
        return
    success = await vpn_provider.revoke_client(client_uuid)
    if success:
        await set_vpn_client_id(user_id, None)
        await message.answer(f"✅ Ключ пользователя {user_id} отозван")
    else:
        await message.answer("❌ Не удалось отозвать ключ")