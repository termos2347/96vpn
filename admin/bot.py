import asyncio
import logging
from collections import deque
from datetime import datetime, timedelta, timezone
from io import BytesIO

from aiogram import F, Bot, Dispatcher, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import BotCommand, BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select, text, func

from config import ADMIN_BOT_TOKEN, ADMIN_CHAT_ID, TOKEN as MAIN_BOT_TOKEN
from handlers import get_vpn_manager
from db.base import engine, AsyncSessionLocal
from db.models import BotUser
from db.crud import (
    get_or_create_bot_user, get_user_vpn_data, set_vpn_client_id,
    is_vpn_active, get_vpn_client_id, update_vpn_subscription
)
from services.vpn_manager import VPNManager
from .servers import router as servers_router
from handlers import get_server_pool

logger = logging.getLogger(__name__)

error_log = deque(maxlen=10)
admin_bot: Bot | None = None
main_bot: Bot | None = None

# ---------- Состояние для рассылки ----------
class BroadcastStates(StatesGroup):
    confirm = State()

# Словарь для флагов отмены рассылки (key: chat_id)
_broadcast_cancel_flags = {}

# ---------- Вспомогательные функции ----------
async def send_admin_alert(message: str):
    global admin_bot
    if not admin_bot or not ADMIN_CHAT_ID:
        logger.warning("Admin bot not initialized, alert not sent")
        return
    try:
        await admin_bot.send_message(ADMIN_CHAT_ID, f"🚨 {message}")
    except Exception as e:
        logger.error("Failed to send admin alert", exc_info=True)

async def startup():
    global admin_bot, main_bot
    admin_bot = Bot(token=ADMIN_BOT_TOKEN)
    main_bot = Bot(token=MAIN_BOT_TOKEN)
    await admin_bot.set_my_commands([
        BotCommand(command="health", description="Проверка состояния"),
        BotCommand(command="errors", description="Последние ошибки"),
        BotCommand(command="broadcast", description="Рассылка текста или медиа (reply на сообщение)"),
        BotCommand(command="userinfo", description="Информация о пользователе (telegram_id)"),
        BotCommand(command="grant", description="Выдать/продлить VPN-подписку (telegram_id дни)"),
        BotCommand(command="revoke", description="Отозвать VPN-подписку (telegram_id)"),
        BotCommand(command="stats", description="Статистика по подпискам"),
        BotCommand(command="addserver", description="Добавить VPN-сервер в пул"),
        BotCommand(command="listservers", description="Список всех серверов"),
        BotCommand(command="removeserver", description="Удалить сервер по ID"),
        BotCommand(command="serversetactive", description="Включить/отключить сервер"),
        BotCommand(command="menu", description="Показать список команд"),
    ])
    logger.info("Admin bot started")

async def shutdown():
    global admin_bot, main_bot
    if admin_bot:
        await admin_bot.session.close()
        admin_bot = None
    if main_bot:
        await main_bot.session.close()
        main_bot = None

dp = Dispatcher()
dp.include_router(servers_router)

# ---------- Базовые команды ----------
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("🛡️ Админ-бот 96VPN. Все команды: /menu")

@dp.message(Command("menu"))
async def cmd_menu(message: types.Message):
    text = (
        "📋 Доступные команды:\n\n"
        "/health – состояние системы\n"
        "/errors – последние ошибки\n"
        "/broadcast – рассылка (reply на сообщение)\n"
        "/userinfo <telegram_id> – информация о пользователе\n"
        "/grant <telegram_id> <days> – выдать/продлить VPN\n"
        "/revoke <telegram_id> – отозвать VPN\n"
        "/stats – статистика по подпискам\n"
        "/addserver – добавить VPN-сервер в пул\n"
        "/listservers – список всех серверов\n"
        "/removeserver <id> – удалить сервер по ID\n"
        "/serversetactive <id> <0|1> – включить/отключить сервер\n"
    )
    await message.answer(text)

@dp.message(Command("health"))
async def cmd_health(message: types.Message):
    status = "✅ Статус:\n"
    # Проверка базы данных
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        status += "• БД: подключена\n"
    except Exception as e:
        status += f"• БД: ошибка ({e})\n"
    
    # Проверка VPN-панели через пул серверов (без глобального провайдера)
    pool = get_server_pool()
    if pool.servers:
        # Берём первый активный сервер для проверки
        first_server = pool.servers[0]
        provider = await pool.get_provider(first_server.id)
        if provider:
            try:
                if await provider.login():
                    status += "• VPN-панель: авторизована (на одном из серверов)\n"
                else:
                    status += "• VPN-панель: не удалось авторизоваться\n"
            except Exception as e:
                status += f"• VPN-панель: ошибка при авторизации ({e})\n"
        else:
            status += "• VPN-панель: провайдер не найден\n"
    else:
        status += "• VPN-панель: нет активных серверов в пуле\n"
    
    await message.answer(status)

@dp.message(Command("errors"))
async def cmd_errors(message: types.Message):
    if not error_log:
        await message.answer("✅ Нет сохранённых ошибок.")
        return
    text_lines = "📋 Последние ошибки:\n"
    for i, err in enumerate(reversed(error_log), 1):
        text_lines += f"{i}. {err}\n"
    await message.answer(text_lines)

# ---------- Рассылка с подтверждением и ограничениями ----------
@dp.message(Command("broadcast"))
async def cmd_broadcast(message: types.Message, state: FSMContext):
    if str(message.from_user.id) != ADMIN_CHAT_ID:
        await message.answer("❌ Нет доступа.")
        return
    if not message.reply_to_message:
        await message.answer("❗ Ответьте на сообщение, которое нужно разослать, и пришлите /broadcast.")
        return

    reply = message.reply_to_message
    await state.update_data(
        reply_message_id=reply.message_id,
        reply_chat_id=reply.chat.id
    )
    await state.set_state(BroadcastStates.confirm)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, начать рассылку", callback_data="broadcast_confirm")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast_cancel")]
    ])
    await message.answer(
        "⚠️ Вы уверены, что хотите разослать это сообщение ВСЕМ пользователям?\n"
        "Это действие нельзя отменить.\n\n"
        "Нажмите 'Да, начать рассылку' для запуска.",
        reply_markup=kb
    )

@dp.callback_query(StateFilter(BroadcastStates.confirm), F.data.startswith("broadcast_"))
async def broadcast_confirm(callback: types.CallbackQuery, state: FSMContext):
    if str(callback.from_user.id) != ADMIN_CHAT_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return

    action = callback.data.split("_")[1]
    if action == "cancel":
        await state.clear()
        await callback.message.edit_text("❌ Рассылка отменена.")
        await callback.answer()
        return

    # action == "confirm"
    await callback.message.edit_text("⏳ Подготовка к рассылке...")
    await callback.answer()

    data = await state.get_data()
    reply_msg_id = data.get("reply_message_id")
    reply_chat_id = data.get("reply_chat_id")
    await state.clear()

    # Получаем содержимое сообщения
    try:
        # Копируем сообщение в текущий чат, чтобы извлечь медиа
        original_msg = await callback.bot.forward_message(
            chat_id=callback.message.chat.id,
            from_chat_id=reply_chat_id,
            message_id=reply_msg_id
        )
        text = original_msg.text or original_msg.caption
        media_type = None
        file_id = None
        filename = "file"
        if original_msg.photo:
            media_type = "photo"
            file_id = original_msg.photo[-1].file_id
            filename = "image.jpg"
        elif original_msg.video:
            media_type = "video"
            file_id = original_msg.video.file_id
            filename = "video.mp4"
        elif original_msg.animation:
            media_type = "animation"
            file_id = original_msg.animation.file_id
            filename = "animation.gif"
        elif original_msg.document:
            media_type = "document"
            file_id = original_msg.document.file_id
            if original_msg.document.file_name:
                filename = original_msg.document.file_name
        await original_msg.delete()
    except Exception as e:
        logger.error("Failed to fetch original message for broadcast", exc_info=True)
        await callback.message.answer(f"❌ Не удалось получить сообщение для рассылки: {e}")
        return

    # Получаем список пользователей
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(BotUser.telegram_id))
        user_ids = [row[0] for row in result.all()]

    if not user_ids:
        await callback.message.answer("Нет пользователей для рассылки.")
        return

    total = len(user_ids)
    cancel_flag_key = callback.message.chat.id
    _broadcast_cancel_flags[cancel_flag_key] = False

    cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛑 Остановить рассылку", callback_data=f"stop_broadcast_{cancel_flag_key}")]
    ])
    status_msg = await callback.message.answer(
        f"📡 Начинаю рассылку {total} пользователям... (0/{total})",
        reply_markup=cancel_kb
    )

    # Скачиваем медиа (если есть) один раз
    media_bytes = None
    if media_type:
        try:
            buf = BytesIO()
            await admin_bot.download(file_id, destination=buf)
            media_bytes = buf.getvalue()
        except Exception as e:
            logger.error("Failed to download media for broadcast", exc_info=True)
            await status_msg.edit_text(f"❌ Не удалось скачать файл: {e}")
            _broadcast_cancel_flags.pop(cancel_flag_key, None)
            return

    # Параметры ограничения скорости
    SEMAPHORE_LIMIT = 5
    DELAY_BETWEEN_BATCH = 1
    semaphore = asyncio.Semaphore(SEMAPHORE_LIMIT)

    async def send_to_user(uid: int, bot_instance: Bot):
        async with semaphore:
            try:
                if media_type == "photo":
                    await bot_instance.send_photo(uid, BufferedInputFile(media_bytes, filename=filename), caption=text)
                elif media_type == "video":
                    await bot_instance.send_video(uid, BufferedInputFile(media_bytes, filename=filename), caption=text)
                elif media_type == "animation":
                    await bot_instance.send_animation(uid, BufferedInputFile(media_bytes, filename=filename), caption=text)
                elif media_type == "document":
                    await bot_instance.send_document(uid, BufferedInputFile(media_bytes, filename=filename), caption=text)
                else:
                    await bot_instance.send_message(uid, text)
                return True
            except Exception as e:
                logger.debug(f"Broadcast failed for {uid}: {e}")
                return False

    success = 0
    fail = 0
    # Отправляем пачками
    for i in range(0, total, SEMAPHORE_LIMIT):
        if _broadcast_cancel_flags.get(cancel_flag_key, False):
            await status_msg.edit_text(f"🛑 Рассылка остановлена пользователем. Отправлено: {success}, ошибок: {fail}")
            _broadcast_cancel_flags.pop(cancel_flag_key, None)
            return

        batch = user_ids[i:i+SEMAPHORE_LIMIT]
        tasks = [send_to_user(uid, main_bot) for uid in batch]
        results = await asyncio.gather(*tasks)
        success += sum(results)
        fail += len(results) - sum(results)

        if (i + SEMAPHORE_LIMIT) % 50 == 0 or i + SEMAPHORE_LIMIT >= total:
            try:
                await status_msg.edit_text(
                    f"📡 Рассылка: {success+fail}/{total} (✅ {success}, ❌ {fail})",
                    reply_markup=cancel_kb
                )
            except Exception:
                pass  # если сообщение не изменилось, игнорируем
        await asyncio.sleep(DELAY_BETWEEN_BATCH)

    _broadcast_cancel_flags.pop(cancel_flag_key, None)
    await status_msg.edit_text(
        f"✅ Рассылка завершена.\n"
        f"📤 Отправлено: {success}\n"
        f"❌ Ошибок: {fail}\n"
        f"👥 Всего пользователей: {total}"
    )

@dp.callback_query(lambda c: c.data and c.data.startswith("stop_broadcast_"))
async def stop_broadcast(callback: types.CallbackQuery):
    if str(callback.from_user.id) != ADMIN_CHAT_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return
    key = int(callback.data.split("_")[2])
    _broadcast_cancel_flags[key] = True
    await callback.answer("⏳ Останавливаю рассылку...")
    await callback.message.edit_reply_markup(reply_markup=None)

# ---------- Управление пользователями ----------
@dp.message(Command("userinfo"))
async def cmd_userinfo(message: types.Message):
    if str(message.from_user.id) != ADMIN_CHAT_ID:
        await message.answer("❌ Нет доступа.")
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("❗ Используйте: /userinfo <telegram_id>")
        return
    try:
        tid = int(args[1])
    except ValueError:
        await message.answer("❌ Неверный формат telegram_id.")
        return

    data = await get_user_vpn_data(tid)
    if not data:
        await message.answer("❌ Пользователь не найден.")
        return

    now = datetime.now(timezone.utc)
    vpn_end = data["vpn_subscription_end"]
    bypass_end = data["bypass_subscription_end"]
    vpn_left = (vpn_end - now).days if vpn_end and vpn_end > now else 0
    bypass_left = (bypass_end - now).days if bypass_end and bypass_end > now else 0
    vpn_active = vpn_left > 0
    bypass_active = bypass_left > 0
    vpn_key = data["vpn_client_id"] or "не создан"

    text = (
        f"👤 Пользователь: {tid}\n"
        f"🔹 Username: ... (можно получить отдельно, если нужно)\n"
        f"📧 Email: ...\n\n"
        f"🚀 VPN-подписка: {'✅ активна' if vpn_active else '❌ неактивна'}\n"
        f"   Окончание: {vpn_end.strftime('%d.%m.%Y') if vpn_end else '—'}\n"
        f"   Осталось: {vpn_left} дн.\n"
        f"   Ключ: {vpn_key}\n\n"
        f"🛡️ Обход DPI: {'✅ активен' if bypass_active else '❌ не активен'}\n"
        f"   Окончание: {bypass_end.strftime('%d.%m.%Y') if bypass_end else '—'}\n"
        f"   Осталось: {bypass_left} дн."
    )
    await message.answer(text)

@dp.message(Command("grant"))
async def cmd_grant(message: types.Message):
    if str(message.from_user.id) != ADMIN_CHAT_ID:
        await message.answer("❌ Нет доступа.")
        return
    args = message.text.split()
    if len(args) < 3:
        await message.answer("❗ Используйте: /grant <telegram_id> <days>")
        return
    try:
        tid = int(args[1])
        days = int(args[2])
    except ValueError:
        await message.answer("❌ Неверный формат.")
        return
    if days <= 0:
        await message.answer("❌ Дни должны быть положительным числом.")
        return

    # Вся операция в одной сессии
    async with AsyncSessionLocal() as session:
        async with session.begin():
            user = await update_vpn_subscription(session, tid, days)
            # Проверяем, есть ли активный ключ
            if user.vpn_client_id and user.vpn_subscription_end > datetime.now(timezone.utc):
                # ключ уже есть – просто продлили
                end_date = user.vpn_subscription_end.strftime('%d.%m.%Y')
                await message.answer(f"✅ VPN-подписка для {tid} продлена на {days} дн. до {end_date}. Ключ не изменялся.")
            else:
                pass

    # После выхода из сессии создаём ключ (если нужно)
    if not (user.vpn_client_id and user.vpn_subscription_end > datetime.now(timezone.utc)):
        manager = get_vpn_manager()
        link = await manager.create_key(tid, days)
        if link:
            await message.answer(f"✅ VPN-подписка для {tid} активирована на {days} дн., ключ: {link}")
        else:
            await message.answer(f"✅ VPN-подписка для {tid} активирована, но ключ не создан.")

# Аналогично revoke – открываем сессию, обновляем поля, затем коммитим.
@dp.message(Command("revoke"))
async def cmd_revoke(message: types.Message):
    if str(message.from_user.id) != ADMIN_CHAT_ID:
        await message.answer("❌ Нет доступа.")
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("❗ Используйте: /revoke <telegram_id>")
        return
    try:
        tid = int(args[1])
    except ValueError:
        await message.answer("❌ Неверный формат.")
        return

    manager = get_vpn_manager()
    success = await manager.revoke_key(tid)  # внутри сам создаст сессию
    if success:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                user = await get_or_create_bot_user(session, tid)
                user.vpn_subscription_end = datetime.now(timezone.utc) - timedelta(days=1)
        await message.answer(f"✅ VPN-подписка для {tid} отозвана.")
    else:
        await message.answer(f"⚠️ Не удалось отозвать ключ для {tid}.")

# ---------- Статистика ----------
@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    if str(message.from_user.id) != ADMIN_CHAT_ID:
        await message.answer("❌ Нет доступа.")
        return

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)
    week_later = now + timedelta(days=7)
    month_later = now + timedelta(days=30)

    # Все запросы выполняем в одной сессии
    async with AsyncSessionLocal() as session:
        # Общее количество пользователей
        total_res = await session.execute(select(func.count(BotUser.id)))
        total = total_res.scalar() or 0

        # Новые сегодня
        new_today_res = await session.execute(
            select(func.count(BotUser.id)).where(BotUser.created_at >= today_start)
        )
        new_today = new_today_res.scalar() or 0

        # Новые за неделю
        new_week_res = await session.execute(
            select(func.count(BotUser.id)).where(BotUser.created_at >= week_ago)
        )
        new_week = new_week_res.scalar() or 0

        # Новые за месяц
        new_month_res = await session.execute(
            select(func.count(BotUser.id)).where(BotUser.created_at >= month_ago)
        )
        new_month = new_month_res.scalar() or 0

        # Активные подписки (vpn_subscription_end > now)
        active_res = await session.execute(
            select(func.count(BotUser.id)).where(BotUser.vpn_subscription_end > now)
        )
        active = active_res.scalar() or 0

        # Истекают сегодня (до конца дня)
        expire_today_res = await session.execute(
            select(func.count(BotUser.id)).where(
                BotUser.vpn_subscription_end > now,
                BotUser.vpn_subscription_end <= today_start + timedelta(days=1)
            )
        )
        expire_today = expire_today_res.scalar() or 0

        # Истекают в течение 7 дней
        expire_7d_res = await session.execute(
            select(func.count(BotUser.id)).where(
                BotUser.vpn_subscription_end > now,
                BotUser.vpn_subscription_end <= week_later
            )
        )
        expire_7d = expire_7d_res.scalar() or 0

        # Истекают в течение 30 дней
        expire_30d_res = await session.execute(
            select(func.count(BotUser.id)).where(
                BotUser.vpn_subscription_end > now,
                BotUser.vpn_subscription_end <= month_later
            )
        )
        expire_30d = expire_30d_res.scalar() or 0

        # Истекшие (vpn_subscription_end <= now и не NULL)
        expired_res = await session.execute(
            select(func.count(BotUser.id)).where(
                BotUser.vpn_subscription_end <= now,
                BotUser.vpn_subscription_end.isnot(None)
            )
        )
        expired = expired_res.scalar() or 0

        # Без подписки (vpn_subscription_end IS NULL)
        no_sub_res = await session.execute(
            select(func.count(BotUser.id)).where(BotUser.vpn_subscription_end.is_(None))
        )
        no_sub = no_sub_res.scalar() or 0

        # Средний остаток дней у активных (используем функцию avg)
        avg_days_res = await session.execute(
            select(func.avg(BotUser.vpn_subscription_end - now)).where(
                BotUser.vpn_subscription_end > now
            )
        )
        avg_days_val = avg_days_res.scalar()
        avg_days = int(avg_days_val) if avg_days_val is not None else 0

    text = (
        "📊 Статистика VPN-клиентов:\n"
        f"• Всего пользователей: {total}\n"
        f"• Новые сегодня: {new_today}\n"
        f"• Новые за 7 дней: {new_week}\n"
        f"• Новые за 30 дней: {new_month}\n\n"
        f"🚀 Активные подписки: {active}\n"
        f"   – истекают сегодня: {expire_today}\n"
        f"   – истекают в течение 7 дн.: {expire_7d}\n"
        f"   – истекают в течение 30 дн.: {expire_30d}\n"
        f"   – средний остаток: {avg_days} дн.\n\n"
        f"❌ Истекшие подписки: {expired}\n"
        f"⚪ Без подписки: {no_sub}"
    )
    await message.answer(text)