from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.types import KeyboardButton
router = Router()
# Функция для создания главного меню


def main_kb():
    kb = [
        [KeyboardButton(text="ℹ️ Инфо"), KeyboardButton(text="🚀 Подключить VPN")],
        [KeyboardButton(text="💳 Оплатить VPN"), KeyboardButton(text="🛡️ Обход блокировок")],
        [KeyboardButton(text="🦾 Оплата блокировки"), KeyboardButton(text="🆓 Бесплатный прокси")]
    ]
    return types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)
    return types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

@router.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "Добро пожаловать! Выберите нужный раздел в меню ниже:",
        reply_markup=main_kb()
    )

@router.message(F.text == "ℹ️ Инфо")
async def info(message: types.Message):
    await message.answer("Здесь будет информация о нашем сервисе, локациях серверов и протоколах.")

@router.message(F.text == "🚀 Подключить VPN")
async def connect_vpn(message: types.Message):
    await message.answer("Вы получите настройки для подключения (VLESS/Shadowsocks) после выбора тарифа.")

@router.message(F.text == "💳 Оплатить VPN")
async def pay_vpn(message: types.Message):
    await message.answer("Тут будет выбор периода подписки и переход к оплате.")

@router.message(F.text == "🛡️ Обход блокировок")
async def bypass(message: types.Message):
    await message.answer("Этот режим обеспечит полный доступ ко всем ресурсам, обходя глубокую фильтрацию трафика (DPI).")

@router.message(F.text == "🦾 Оплата блокировки")
async def pay_bypass(message: types.Message):
    await message.answer("Оплата расширенного доступа для полной разблокировки связи.")

@router.message(F.text == "🆓 Бесплатный прокси")
async def free_proxy(message: types.Message):
    await message.answer("Ваш бесплатный прокси: `tg://proxy?server=...` (скоро добавим рабочие ссылки).")
