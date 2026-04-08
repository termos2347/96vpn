from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.types import KeyboardButton

router = Router()

# Функция для создания главного меню
def main_kb():
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
        reply_markup=main_kb()
    )

@router.message(F.text == "ℹ️ Инфо")
async def info(message: types.Message):
    await message.answer("Информация о сервисе: здесь будут описаны тарифы, серверы и преимущества.")

@router.message(F.text == "🚀 Подключить VPN")
async def connect_vpn(message: types.Message):
    await message.answer("Вы получите настройки для подключения (VLESS/Shadowsocks) после активации подписки.")

@router.message(F.text == "💳 Оплатить VPN")
async def pay_vpn(message: types.Message):
    await message.answer("Здесь будет выбор тарифа и переход к оплате (скоро появится).")

@router.message(F.text == "🛡️ Подключить обход")
async def connect_bypass(message: types.Message):
    await message.answer("Режим обхода блокировок (DPI). Подключение будет доступно после оплаты.")

@router.message(F.text == "💰 Оплатить обход")
async def pay_bypass(message: types.Message):
    await message.answer("Оплата доступа к обходу блокировок. Скоро появится возможность оплаты.")

@router.message(F.text == "🆓 Прокси")
async def free_proxy(message: types.Message):
    await message.answer("Бесплатный прокси: `tg://proxy?server=...` (ссылка появится позже).", parse_mode="Markdown")