import logging
from datetime import datetime, timezone

from aiogram import Router, F, types
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command

from services.vpn_manager import get_vpn_manager
from db.crud import get_or_create_bot_user
from db.base import AsyncSessionLocal
from config import settings

logger = logging.getLogger(__name__)
router = Router()

# ---------- Клавиатура главного меню (без Bypass) ----------
def main_keyboard() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text="🚀 Подключить VPN")],
        [KeyboardButton(text="📋 Моя подписка"), KeyboardButton(text="❓ Помощь")],
        [KeyboardButton(text="💳 Оплатить VPN")],
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# ---------- Инлайн-клавиатура для выбора периода (только VPN) ----------
def period_keyboard() -> InlineKeyboardMarkup:
    periods = settings.PERIOD_DAYS
    buttons = []
    for key, days in periods.items():
        label = f"{days} дней"
        callback_data = f"select_vpn_{key}"
        buttons.append([InlineKeyboardButton(text=label, callback_data=callback_data)])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ---------- Команда /start ----------
@router.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or "без username"
    async with AsyncSessionLocal() as session:
        user = await get_or_create_bot_user(session, user_id)
        if not user.username:
            user.username = username
            await session.commit()

    await message.answer(
        f"👋 Привет, {message.from_user.first_name}!\n\n"
        "Я бот для управления VPN-подписками.\n"
        "Выбери действие в меню ниже:",
        reply_markup=main_keyboard()
    )

# ---------- Обработчик кнопки "🚀 Подключить VPN" ----------
@router.message(F.text == "🚀 Подключить VPN")
async def handle_connect_vpn(message: Message):
    user_id = message.from_user.id
    vpn_manager = get_vpn_manager()
    if not vpn_manager:
        await message.answer("❌ VPN-сервис временно недоступен. Попробуйте позже.")
        return

    link = await vpn_manager.get_or_create_link(user_id)
    if link:
        await message.answer(
            f"🔗 Ваша VPN-ссылка для подключения:\n`{link}`\n\n"
            "Скопируйте её и вставьте в VPN-приложение (например, V2Ray, Shadowrocket, Nekoray).",
            parse_mode="Markdown"
        )
    else:
        await message.answer(
            "❌ У вас нет активной VPN-подписки.\n"
            "Оплатите подписку в разделе 💳 Оплатить VPN.",
            reply_markup=main_keyboard()
        )

# ---------- Обработчик кнопки "📋 Моя подписка" ----------
@router.message(F.text == "📋 Моя подписка")
async def handle_my_subscription(message: Message):
    user_id = message.from_user.id
    async with AsyncSessionLocal() as session:
        user = await get_or_create_bot_user(session, user_id)
        now = datetime.now(timezone.utc)
        vpn_end = user.vpn_subscription_end

        text = "📋 *Ваша подписка:*\n\n"
        if vpn_end and vpn_end > now:
            days_left = (vpn_end - now).days
            text += f"✅ *VPN:* активна до {vpn_end.strftime('%d.%m.%Y')} (осталось {days_left} дн.)\n"
        else:
            text += "❌ *VPN:* не активна\n"

        if user.vpn_client_id:
            text += f"\n🔑 Ваш VPN-клиент ID: `{user.vpn_client_id[:8]}...`"

        await message.answer(text, parse_mode="Markdown", reply_markup=main_keyboard())

# ---------- Обработчик кнопки "❓ Помощь" ----------
@router.message(F.text == "❓ Помощь")
async def handle_help(message: Message):
    text = (
        "❓ Помощь и инструкции\n\n"
        "1. Как подключить VPN?\n"
        "   - Оплатите подписку через раздел 'Оплатить VPN'.\n"
        "   - После оплаты нажмите 'Подключить VPN' – вы получите ссылку.\n"
        "   - Скопируйте ссылку и вставьте в VPN-приложение.\n\n"
        "2. Как оплатить?\n"
        "   - Выберите период подписки, затем перейдите на страницу оплаты.\n\n"
        "3. Если у вас проблемы\n"
        "   - Напишите админу: @support_username (замените на реальный).\n\n"
        "4. Команды бота:\n"
        "   /start – главное меню\n"
        "   /help – эта справка"
    )
    await message.answer(text, reply_markup=main_keyboard())

# ---------- Обработчик кнопки "💳 Оплатить VPN" ----------
@router.message(F.text == "💳 Оплатить VPN")
async def handle_pay_vpn(message: Message):
    await message.answer(
        "Выберите период подписки для VPN:",
        reply_markup=period_keyboard()
    )

# ---------- Обработчик инлайн-кнопок выбора периода ----------
@router.callback_query(F.data.startswith("select_vpn_"))
async def handle_period_selection(callback: types.CallbackQuery):
    _, _, period = callback.data.split("_")
    # Здесь должна быть логика создания платежа через Yookassa
    # Пока просто покажем сообщение и уберём инлайн-клавиатуру
    await callback.message.edit_text(
        f"Вы выбрали VPN на период {period}.\n"
        "Сейчас будет создан платёж..."
    )
    await callback.answer()

# ---------- Обработчик кнопки "🔙 Назад" (исправленный) ----------
@router.callback_query(F.data == "back_to_main")
async def handle_back_to_main(callback: types.CallbackQuery):
    # Удаляем сообщение с выбором периода
    await callback.message.delete()
    # Показываем всплывающее уведомление (не создаёт новое сообщение)
    await callback.answer("Главное меню", show_alert=False)

# ---------- Функция установки команд бота ----------
async def setup_bot_commands(bot):
    """Устанавливает команды для основного бота."""
    commands = [
        types.BotCommand(command="start", description="Главное меню"),
        types.BotCommand(command="help", description="Помощь"),
    ]
    await bot.set_my_commands(commands)
    logger.info("Основные команды бота установлены.")