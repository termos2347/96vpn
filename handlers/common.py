from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import KeyboardButton

router = Router()

def main_keyboard():
    """Главная клавиатура с кнопками"""
    kb = [
        [KeyboardButton(text="🚀 Подключить VPN"), KeyboardButton(text="🛡️ Подключить обход")],
        [KeyboardButton(text="💳 Оплатить VPN"), KeyboardButton(text="💰 Оплатить обход")],
        [KeyboardButton(text="ℹ️ Инфо"), KeyboardButton(text="🆓 Прокси")]
    ]
    return types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

@router.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "Добро пожаловать! Выберите нужный раздел в меню ниже:",
        reply_markup=main_keyboard()
    )