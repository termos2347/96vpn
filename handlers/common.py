# handlers/common.py
import logging
from datetime import datetime, timezone
from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

from handlers.ui import Texts, Keyboards
from services.vpn_manager import get_vpn_manager
from db.crud import get_or_create_bot_user
from db.base import AsyncSessionLocal

logger = logging.getLogger(__name__)
router = Router(name="common")


# ---------- Команда /start ----------
@router.message(Command("start"))
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


# ---------- Команда /help (дополнительно) ----------
@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        Texts.help_info(),
        parse_mode="Markdown",
        reply_markup=Keyboards.back_to_main_inline()
    )


# ---------- Обработчик кнопки "🚀 Купить / Продлить VPN" ----------
@router.message(F.text == "🚀 Купить / Продлить VPN")
async def handle_buy_vpn(message: Message):
    await message.answer(
        Texts.tariff_selection(),
        reply_markup=Keyboards.tariff_selection()
    )


# ---------- Обработчик кнопки "🔑 Мои Ключи" ----------
@router.message(F.text == "🔑 Мои Ключи")
async def handle_my_keys(message: Message):
    user_id = message.from_user.id
    vpn_manager = get_vpn_manager()
    if not vpn_manager:
        await message.answer(Texts.vpn_not_available())
        return

    link = await vpn_manager.get_or_create_link(user_id)
    await message.answer(
        Texts.my_keys(link),
        parse_mode="Markdown",
        reply_markup=Keyboards.back_to_main_inline()
    )


# ---------- Обработчик кнопки "ℹ️ Инструкция и Поддержка" ----------
@router.message(F.text == "ℹ️ Инструкция и Поддержка")
async def handle_help(message: Message):
    await message.answer(
        Texts.help_info(),
        reply_markup=Keyboards.back_to_main_inline()
    )


# ---------- Команда /vpn (перенесена из subscription) ----------
@router.message(Command("vpn"))
async def cmd_vpn(message: Message):
    # Просто показываем статус и кнопки
    user_id = message.from_user.id
    async with AsyncSessionLocal() as session:
        user = await get_or_create_bot_user(session, user_id)
        vpn_end = user.vpn_subscription_end
    await message.answer(
        Texts.main_menu(message.from_user.first_name, vpn_end),
        reply_markup=Keyboards.main_menu()
    )


# ---------- Команда /getlink (перенесена из subscription) ----------
@router.message(Command("getlink"))
async def cmd_getlink(message: Message):
    user_id = message.from_user.id
    vpn_manager = get_vpn_manager()
    if not vpn_manager:
        await message.answer(Texts.vpn_not_available())
        return

    link = await vpn_manager.get_or_create_link(user_id)
    if link is None:
        await message.answer(Texts.no_active_subscription())
        return

    await message.answer(
        f"🔗 Ваша ссылка для подключения:\n`{link}`",
        parse_mode="Markdown"
    )


# ---------- Обработчики инлайн-кнопок (возврат в главное меню) ----------
@router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery):
    await callback.message.delete()
    # Отправляем новое сообщение с главным меню
    user_id = callback.from_user.id
    async with AsyncSessionLocal() as session:
        user = await get_or_create_bot_user(session, user_id)
        vpn_end = user.vpn_subscription_end
    await callback.message.answer(
        Texts.main_menu(callback.from_user.first_name, vpn_end),
        reply_markup=Keyboards.main_menu()
    )
    await callback.answer()


@router.callback_query(F.data == "back_to_tariffs")
async def back_to_tariffs(callback: CallbackQuery):
    await callback.message.edit_text(
        Texts.tariff_selection(),
        reply_markup=Keyboards.tariff_selection()
    )
    await callback.answer()


# ---------- Установка команд бота ----------
async def setup_bot_commands(bot):
    """Устанавливает команды для основного бота."""
    commands = [
        types.BotCommand(command="start", description="Главное меню"),
        types.BotCommand(command="help", description="Помощь"),
        types.BotCommand(command="vpn", description="Моя подписка"),
        types.BotCommand(command="getlink", description="Получить ключ VPN"),
    ]
    await bot.set_my_commands(commands)
    logger.info("Основные команды бота установлены.")