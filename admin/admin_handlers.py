from aiogram import Router, types
from aiogram.filters import Command

router = Router()

@router.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id == 123456789:  # Замените на свой ID
        await message.answer("Админ-панель: пока только заглушка.")
    else:
        await message.answer("У вас нет доступа.")