from aiogram import Router, Bot
from aiogram.types import BotCommand, Message
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

router = Router()

# ------------------------------------------------------------------
# Клавиатуры (если используются)
# ------------------------------------------------------------------
def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Главная клавиатура с кнопками для пользователя."""
    buttons = [
        [KeyboardButton(text="💳 Оплатить VPN")],
        [KeyboardButton(text="🔗 Подключить VPN")],
        [KeyboardButton(text="📋 Моя подписка")],
        [KeyboardButton(text="🆘 Помощь")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# ------------------------------------------------------------------
# Команды
# ------------------------------------------------------------------
@router.message(Command("start"))
async def cmd_start(message: Message):
    """Обработчик команды /start."""
    await message.answer(
        "👋 Добро пожаловать в VPN-бот!\n"
        "Выберите действие:",
        reply_markup=get_main_keyboard()
    )

@router.message(Command("help"))
async def cmd_help(message: Message):
    """Обработчик команды /help."""
    await message.answer(
        "📖 Доступные команды:\n"
        "/start - Главное меню\n"
        "/pay - Перейти к оплате VPN\n"
        "/my - Проверить статус подписки\n"
        "/help - Эта справка\n\n"
        "Также вы можете использовать кнопки под полем ввода."
    )

# Можно добавить другие общие хэндлеры, например, для текстовых кнопок,
# но они обычно находятся в отдельных файлах (payment.py, profile.py и т.д.)

# ------------------------------------------------------------------
# Установка команд для меню бота
# ------------------------------------------------------------------
async def setup_bot_commands(bot: Bot):
    """Устанавливает список команд, отображаемых в меню бота."""
    commands = [
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="help", description="Помощь"),
        BotCommand(command="pay", description="Оплатить VPN"),
        BotCommand(command="my", description="Моя подписка"),
    ]
    await bot.set_my_commands(commands)