# handlers/common.py
import logging

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from config import settings
from db.base import AsyncSessionLocal
from db.crud import get_or_create_bot_user
from handlers.ui import Keyboards, Texts
from services.vpn_manager import get_vpn_manager
from utils.decorators import rate_limit

logger = logging.getLogger(__name__)
router = Router(name="common")


@router.message(Command("start"))
@rate_limit(max_per_minute=settings.RATE_LIMIT_START)
async def cmd_start(message: Message):
    if message.from_user is None:
        return
    user = message.from_user
    user_id = user.id

    # BUGFIX: оборачиваем в session.begin() — иначе новый пользователь
    # без username не сохранялся (условие апдейта ложно → commit не
    # вызывался, INSERT откатывался при session.close()).
    async with AsyncSessionLocal() as session, session.begin():
        db_user = await get_or_create_bot_user(session, user_id)
        if db_user.username != user.username:
            db_user.username = user.username
        vpn_end = db_user.vpn_subscription_end

    await message.answer(
        Texts.main_menu(user.first_name, vpn_end),
        reply_markup=Keyboards.main_menu(),
    )


@router.message(F.text == "🚀 Оплатить подписку")
@rate_limit(max_per_minute=settings.RATE_LIMIT_BUY_VPN)
async def handle_buy_vpn(message: Message):
    # Оплата только в рублях — сразу показываем тарифы
    await message.answer(
        Texts.tariff_selection("rub"),
        reply_markup=Keyboards.tariff_selection("rub"),
    )


@router.message(F.text == "🔑 Мои Ключи")
@rate_limit(max_per_minute=settings.RATE_LIMIT_MY_KEYS)
async def handle_my_keys(message: Message):
    if message.from_user is None:
        return
    user_id = message.from_user.id

    vpn_manager = get_vpn_manager()
    if not vpn_manager:
        await message.answer(Texts.vpn_not_available())
        return

    link = await vpn_manager.get_or_create_link(user_id)
    await message.answer(Texts.my_keys(link), parse_mode="Markdown")


@router.message(F.text == "ℹ️ Инструкция и Поддержка")
@rate_limit(max_per_minute=settings.RATE_LIMIT_HELP)
async def handle_help(message: Message):
    await message.answer(Texts.help_info())


@router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery):
    # В aiogram 3 callback.message может быть Message | InaccessibleMessage | None
    if not isinstance(callback.message, Message):
        await callback.answer("Сообщение устарело", show_alert=True)
        return

    await callback.message.delete()

    user_id = callback.from_user.id
    # BUGFIX: явный begin() — гарантирует сохранение нового пользователя
    # и обновление username. Раньше commit не вызывался вообще, поэтому
    # новый пользователь не сохранялся, а смена username не применялась.
    async with AsyncSessionLocal() as session, session.begin():
        db_user = await get_or_create_bot_user(session, user_id)
        if db_user.username != callback.from_user.username:
            db_user.username = callback.from_user.username
        vpn_end = db_user.vpn_subscription_end

    await callback.message.answer(
        Texts.main_menu(callback.from_user.first_name, vpn_end),
        reply_markup=Keyboards.main_menu(),
    )
    await callback.answer()


async def setup_bot_commands(bot):
    commands = [
        types.BotCommand(command="start", description="Главное меню"),
    ]
    await bot.set_my_commands(commands)
    logger.debug("Main bot commands set")
