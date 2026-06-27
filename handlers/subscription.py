import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from handlers import get_vpn_manager
from utils.decorators import rate_limit
from db.crud import get_or_create_bot_user
from db.base import AsyncSessionLocal

logger = logging.getLogger(__name__)
router = Router(name="subscription")

# ------------------------------------------------------------
# Локальные функции для клавиатур (без внешних импортов)
# ------------------------------------------------------------
def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Главное меню с основными действиями."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🚀 Подключить VPN", callback_data="connect_vpn"),
                InlineKeyboardButton(text="💳 Оплатить VPN", callback_data="pay_vpn")
            ],
            [
                InlineKeyboardButton(text="📊 Мой статус", callback_data="status"),
                InlineKeyboardButton(text="❓ Помощь", callback_data="help")
            ]
        ]
    )

def get_payment_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для выбора тарифа."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="1 месяц (199₽)", callback_data="pay_vpn_1m"),
                InlineKeyboardButton(text="3 месяца (499₽)", callback_data="pay_vpn_3m")
            ],
            [
                InlineKeyboardButton(text="6 месяцев (899₽)", callback_data="pay_vpn_6m"),
                InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")
            ]
        ]
    )

# ------------------------------------------------------------
# Команда /vpn
# ------------------------------------------------------------
@router.message(Command("vpn"))
@rate_limit(max_per_minute=3)
async def cmd_vpn(message: Message, state: FSMContext):
    user_id = message.from_user.id
    async with AsyncSessionLocal() as session:
        user = await get_or_create_bot_user(session, user_id)

    if user.vpn_subscription_end:
        end_date = user.vpn_subscription_end.strftime("%d.%m.%Y")
        status_text = f"✅ Ваша VPN-подписка активна до **{end_date}**."
    else:
        status_text = "❌ У вас нет активной VPN-подписки."

    await message.answer(
        f"📡 **VPN-подписка**\n\n{status_text}\n\n"
        "Нажмите «Подключить VPN», чтобы получить ссылку для настройки.",
        reply_markup=get_main_menu_keyboard(),
        parse_mode="Markdown"
    )

# ------------------------------------------------------------
# Обработчик кнопки "Подключить VPN"
# ------------------------------------------------------------
@router.callback_query(F.data == "connect_vpn")
@rate_limit(max_per_minute=2)
async def callback_connect_vpn(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    vpn_manager = get_vpn_manager()

    link = await vpn_manager.get_or_create_link(user_id)

    if link is None:
        await callback.answer(
            "❌ Ваша подписка истекла или отсутствует. Оплатите продление.",
            show_alert=True
        )
        await callback.message.edit_text(
            "⏳ Ваша VPN-подписка неактивна.\n"
            "Пожалуйста, выберите тариф и оплатите продление:",
            reply_markup=get_payment_keyboard()
        )
        return

    await callback.answer("✅ Ссылка получена", show_alert=False)
    await callback.message.edit_text(
        f"🔗 **Ваша ссылка для подключения:**\n\n`{link}`\n\n"
        "Скопируйте её и вставьте в VPN-приложение.",
        parse_mode="Markdown",
        reply_markup=get_main_menu_keyboard()
    )

# ------------------------------------------------------------
# Команда /getlink
# ------------------------------------------------------------
@router.message(Command("getlink"))
@rate_limit(max_per_minute=2)
async def cmd_getlink(message: Message):
    user_id = message.from_user.id
    vpn_manager = get_vpn_manager()

    link = await vpn_manager.get_or_create_link(user_id)

    if link is None:
        await message.answer(
            "❌ Ваша VPN-подписка неактивна. Пожалуйста, оплатите продление."
        )
        return

    await message.answer(
        f"🔗 Ваша ссылка для подключения:\n`{link}`",
        parse_mode="Markdown"
    )