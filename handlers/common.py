# handlers/common.py
import logging
from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

from handlers.ui import Texts, Keyboards
from services.vpn_manager import get_vpn_manager
from db.crud import get_or_create_bot_user
from db.base import AsyncSessionLocal
from utils.decorators import rate_limit
from config import settings

logger = logging.getLogger(__name__)
router = Router(name="common")


@router.message(Command("start"))
@rate_limit(max_per_minute=settings.RATE_LIMIT_START)
async def cmd_start(message: Message):
    user_id = message.from_user.id
    async with AsyncSessionLocal() as session:
        user = await get_or_create_bot_user(session, user_id)
        if not user.username:
            user.username = message.from_user.username
            await session.commit()
        vpn_end = user.vpn_subscription_end
    await message.answer(
        Texts.main_menu(message.from_user.first_name, vpn_end),
        reply_markup=Keyboards.main_menu()
    )


@router.message(F.text == "🚀 Оплатить подписку")
@rate_limit(max_per_minute=settings.RATE_LIMIT_BUY_VPN)
async def handle_buy_vpn(message: Message):
    await message.answer(
        Texts.currency_selection(),
        reply_markup=Keyboards.currency_selection()
    )


@router.message(F.text == "🔑 Мои Ключи")
@rate_limit(max_per_minute=settings.RATE_LIMIT_MY_KEYS)
async def handle_my_keys(message: Message):
    user_id = message.from_user.id
    vpn_manager = get_vpn_manager()
    if not vpn_manager:
        await message.answer(Texts.vpn_not_available())
        return
    link = await vpn_manager.get_or_create_link(user_id)
    await message.answer(
        Texts.my_keys(link),
        parse_mode="Markdown"
    )


@router.message(F.text == "ℹ️ Инструкция и Поддержка")
@rate_limit(max_per_minute=settings.RATE_LIMIT_HELP)
async def handle_help(message: Message):
    await message.answer(Texts.help_info())


@router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery):
    await callback.message.delete()
    user_id = callback.from_user.id
    async with AsyncSessionLocal() as session:
        user = await get_or_create_bot_user(session, user_id)
        vpn_end = user.vpn_subscription_end
    await callback.message.answer(
        Texts.main_menu(callback.from_user.first_name, vpn_end),
        reply_markup=Keyboards.main_menu()
    )
    await callback.answer()


@router.callback_query(F.data == "back_to_currencies")
async def back_to_currencies(callback: CallbackQuery):
    await callback.message.edit_text(
        Texts.currency_selection(),
        reply_markup=Keyboards.currency_selection()
    )
    await callback.answer()


async def setup_bot_commands(bot):
    commands = [
        types.BotCommand(command="start", description="Главное меню"),
    ]
    await bot.set_my_commands(commands)
    # Логируем только в DEBUG
    logger.debug("Main bot commands set")