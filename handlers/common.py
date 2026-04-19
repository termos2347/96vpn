from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.types import KeyboardButton, BotCommand

router = Router()

# Главная клавиатура
def main_keyboard():
    kb = [
        [KeyboardButton(text="🚀 Подключить VPN"), KeyboardButton(text="🛡️ Подключить обход")],
        [KeyboardButton(text="💳 Оплатить VPN"), KeyboardButton(text="💰 Оплатить обход")],
        [KeyboardButton(text="ℹ️ Инфо"), KeyboardButton(text="🆓 Прокси")],
    ]
    return types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

# Функция для установки команд в кнопку "Меню"
async def setup_bot_commands(bot):
    commands = [
        BotCommand(command="start", description="🚀 Главное меню"),
        # при необходимости добавьте другие команды, например:
        # BotCommand(command="help", description="❓ Помощь"),
    ]
    await bot.set_my_commands(commands)

# Обработчик команды /start
@router.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "Добро пожаловать! Выберите нужный раздел в меню ниже:",
        reply_markup=main_keyboard()
    )

# Обработчик кнопки "ℹ️ Инфо"
@router.message(F.text == "ℹ️ Инфо")
async def info(message: types.Message):
    await message.answer(
        "📌 О сервисе:\n"
        "— Высокоскоростные серверы в 5 странах\n"
        "— Протоколы: VLESS, Shadowsocks, WireGuard\n"
        "— Защита от утечек DNS и IPv6\n"
        "— Круглосуточная поддержка\n\n"
        "По вопросам: @support_username"
    )