import asyncio
import logging
from collections import deque
from datetime import datetime, timedelta, timezone
from io import BytesIO

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import BotCommand, BufferedInputFile
from sqlalchemy import select, text, func

from config import ADMIN_BOT_TOKEN, ADMIN_CHAT_ID, TOKEN as MAIN_BOT_TOKEN
from db.base import engine, AsyncSessionLocal
from db.models import User
from db.crud import (
    get_or_create_user,
    set_vpn_subscription,
    get_vpn_end,
    is_vpn_active,
    set_vpn_client_id,
    get_vpn_client_id,
)
from services.vpn_provider import vpn_provider

logger = logging.getLogger(__name__)

error_log = deque(maxlen=10)
admin_bot: Bot | None = None
main_bot: Bot | None = None

async def send_admin_alert(message: str):
    global admin_bot
    if not admin_bot or not ADMIN_CHAT_ID:
        logger.warning("Admin bot not initialized, alert not sent")
        return
    try:
        await admin_bot.send_message(ADMIN_CHAT_ID, f"🚨 {message}")
    except Exception as e:
        logger.error(f"Failed to send admin alert: {e}")

async def startup():
    global admin_bot, main_bot
    admin_bot = Bot(token=ADMIN_BOT_TOKEN)
    main_bot = Bot(token=MAIN_BOT_TOKEN)
    await admin_bot.set_my_commands([
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="health", description="Проверка состояния"),
        BotCommand(command="errors", description="Последние ошибки"),
        BotCommand(command="broadcast", description="Рассылка текста или медиа (reply на сообщение)"),
        BotCommand(command="userinfo", description="Информация о пользователе (telegram_id)"),
        BotCommand(command="grant", description="Выдать/продлить VPN-подписку (telegram_id дни)"),
        BotCommand(command="revoke", description="Отозвать VPN-подписку (telegram_id)"),
        BotCommand(command="stats", description="Статистика по подпискам"),
        BotCommand(command="menu", description="Список всех команд"),
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
    logger.info("Admin bot stopped")

dp = Dispatcher()

# ---------- /start ----------
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "🛡️ Админ-бот 96VPN. Команды:\n"
        "/health – состояние системы\n"
        "/errors – последние ошибки\n"
        "/broadcast – рассылка (reply на сообщение)\n"
        "/userinfo <telegram_id> – информация о пользователе\n"
        "/grant <telegram_id> <days> – выдать/продлить VPN\n"
        "/revoke <telegram_id> – отозвать VPN\n"
        "/stats – статистика"
    )

# ---------- /health ----------
@dp.message(Command("health"))
async def cmd_health(message: types.Message):
    status = "✅ Статус:\n"
    
    # Проверка БД
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        status += "• БД: подключена\n"
    except Exception as e:
        status += f"• БД: ошибка ({e})\n"
    
    # Проверка VPN-панели
    try:
        if await vpn_provider.login():
            status += "• VPN-панель: авторизована\n"
        else:
            status += "• VPN-панель: не авторизована\n"
    except Exception as e:
        status += f"• VPN-панель: ошибка ({e})\n"
    
    # Проверка веб-сайта (через внутренний URL)
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get("http://localhost:8000/health", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    status += f"• Веб-сайт: доступен (статус: {data.get('status', 'ok')})\n"
                else:
                    status += f"• Веб-сайт: ответ {resp.status}\n"
    except Exception as e:
        status += f"• Веб-сайт: ошибка ({e})\n"
    
    await message.answer(status)

# ---------- /errors ----------
@dp.message(Command("errors"))
async def cmd_errors(message: types.Message):
    if not error_log:
        await message.answer("✅ Нет сохранённых ошибок.")
        return
    text = "📋 Последние ошибки:\n"
    for i, err in enumerate(reversed(error_log), 1):
        text += f"{i}. {err}\n"
    await message.answer(text)

# ---------- /broadcast ----------
@dp.message(Command("broadcast"))
async def cmd_broadcast(message: types.Message):
    if str(message.from_user.id) != ADMIN_CHAT_ID:
        await message.answer("❌ Нет доступа.")
        return

    if not message.reply_to_message:
        await message.answer("❗ Ответьте на сообщение, которое нужно разослать, и пришлите /broadcast.")
        return

    reply = message.reply_to_message
    text_to_send = reply.text or reply.caption

    media_type = None
    file_id = None
    filename = "file"
    if reply.photo:
        media_type = "photo"
        file_id = reply.photo[-1].file_id
        filename = "image.jpg"
    elif reply.video:
        media_type = "video"
        file_id = reply.video.file_id
        filename = "video.mp4"
    elif reply.animation:
        media_type = "animation"
        file_id = reply.animation.file_id
        filename = "animation.gif"
    elif reply.document:
        media_type = "document"
        file_id = reply.document.file_id
        if reply.document.file_name:
            filename = reply.document.file_name

    if not media_type and not text_to_send:
        await message.answer("❗ В отвечаемом сообщении нет ни текста, ни медиа.")
        return

    media_bytes = None
    if media_type:
        try:
            buf = BytesIO()
            await admin_bot.download(file_id, destination=buf)
            media_bytes = buf.getvalue()
        except Exception as e:
            logger.error(f"Failed to download media: {e}")
            await message.answer("❌ Не удалось скачать файл для рассылки.")
            return

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User.user_id).where(
                User.user_id.isnot(None),
                User.source == "bot"
            )
        )
        user_ids = [row[0] for row in result.all()]

    if not user_ids:
        await message.answer("Нет клиентов для рассылки.")
        return

    await message.answer(f"Рассылка на {len(user_ids)} клиентов началась...")
    success = 0
    fail = 0

    for uid in user_ids:
        try:
            if media_type:
                input_file = BufferedInputFile(media_bytes, filename=filename)
                if media_type == "photo":
                    await main_bot.send_photo(uid, input_file, caption=text_to_send)
                elif media_type == "video":
                    await main_bot.send_video(uid, input_file, caption=text_to_send)
                elif media_type == "animation":
                    await main_bot.send_animation(uid, input_file, caption=text_to_send)
                elif media_type == "document":
                    await main_bot.send_document(uid, input_file, caption=text_to_send)
            else:
                await main_bot.send_message(uid, text_to_send)
            success += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.info(f"Broadcast could not deliver to {uid}: {e}")
            fail += 1

    await message.answer(f"✅ Рассылка завершена: отправлено {success}, ошибок {fail}.")

# ---------- /userinfo <telegram_id> ----------
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

    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(tid, session=session)
        if not user:
            await message.answer("❌ Пользователь не найден.")
            return

        vpn_end = user.vpn_subscription_end
        bypass_end = user.bypass_subscription_end
        now = datetime.utcnow()
        vpn_left = (vpn_end - now).days if vpn_end and vpn_end > now else 0
        bypass_left = (bypass_end - now).days if bypass_end and bypass_end > now else 0
        vpn_active = vpn_left > 0
        bypass_active = bypass_left > 0
        vpn_key = user.vpn_client_id or "не создан"

        text = (
            f"👤 Пользователь: {user.user_id}\n"
            f"🔹 Username: @{user.username or '—'}\n"
            f"📧 Email: {user.email or '—'}\n\n"
            f"🚀 VPN-подписка: {'✅ активна' if vpn_active else '❌ неактивна'}\n"
            f"   Окончание: {vpn_end.strftime('%d.%m.%Y') if vpn_end else '—'}\n"
            f"   Осталось: {vpn_left} дн.\n"
            f"   Ключ: {vpn_key}\n\n"
            f"🛡️ Обход DPI: {'✅ активен' if bypass_active else '❌ не активен'}\n"
            f"   Окончание: {bypass_end.strftime('%d.%m.%Y') if bypass_end else '—'}\n"
            f"   Осталось: {bypass_left} дн."
        )
        await message.answer(text)

# ---------- /grant <telegram_id> <days> ----------
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
        await message.answer("❌ Неверный формат аргументов.")
        return

    if days <= 0:
        await message.answer("❌ Дни должны быть положительным числом.")
        return

    from services.vpn_manager import VPNManager

    try:
        async with AsyncSessionLocal() as session:
            user = await get_or_create_user(tid, session=session)

            # Проверяем, есть ли уже активный ключ
            has_active_key = user.vpn_client_id and user.vpn_subscription_end and user.vpn_subscription_end > datetime.utcnow()

            if has_active_key:
                # Просто продлеваем подписку, не трогая ключ
                await set_vpn_subscription(tid, days)
                end_date = user.vpn_subscription_end.strftime('%d.%m.%Y') if user.vpn_subscription_end else "неизвестно"
                await message.answer(f"✅ VPN-подписка для {tid} продлена на {days} дн. до {end_date}. Ключ не изменялся.")
                return

        # Если ключа нет или подписка истекла — создаём/пересоздаём ключ
        await set_vpn_subscription(tid, days)
        manager = VPNManager()
        link = await manager.create_key(tid, days)
        await manager.close()

        async with AsyncSessionLocal() as session:
            user = await get_or_create_user(tid, session=session)
            end_date = user.vpn_subscription_end.strftime('%d.%m.%Y') if user.vpn_subscription_end else "неизвестно"

        msg = f"✅ VPN-подписка для {tid} активирована на {days} дн. до {end_date}."
        if link:
            msg += f"\n🔗 Новый ключ: {link}"
        else:
            msg += "\n⚠️ Ключ не был создан (ошибка)."
        await message.answer(msg)

    except Exception as e:
        logger.error(f"Grant failed for {tid}: {e}")
        await send_admin_alert(f"Ошибка при /grant для {tid}: {e}")
        await message.answer(f"❌ Ошибка: {e}")

# ---------- /revoke <telegram_id> ----------
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
        await message.answer("❌ Неверный формат telegram_id.")
        return

    from services.vpn_manager import VPNManager

    try:
        manager = VPNManager()
        success = await manager.revoke_key(tid)
        await manager.close()

        if success:
            # Сбрасываем дату окончания подписки в прошлое, чтобы подписка считалась неактивной
            async with AsyncSessionLocal() as session:
                user = await get_or_create_user(tid, session=session)
                if user:
                    user.vpn_subscription_end = datetime.utcnow() - timedelta(days=1)
                    await session.commit()
            await message.answer(f"✅ VPN-подписка для {tid} полностью отозвана (ключ удалён, подписка деактивирована).")
        else:
            await message.answer(f"⚠️ Не удалось отозвать ключ для {tid}. Возможно, ключа не было.")
    except Exception as e:
        logger.error(f"Revoke failed for {tid}: {e}")
        await send_admin_alert(f"Ошибка при /revoke для {tid}: {e}")
        await message.answer(f"❌ Ошибка: {e}")

# ---------- /stats ----------
@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    if str(message.from_user.id) != ADMIN_CHAT_ID:
        await message.answer("❌ Нет доступа.")
        return

    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)
    week_later = now + timedelta(days=7)
    month_later = now + timedelta(days=30)

    async with AsyncSessionLocal() as session:
        # Всего пользователей (source == "bot")
        total_res = await session.execute(
            select(func.count(User.id)).where(User.source == "bot")
        )
        total = total_res.scalar() or 0

        # Новые пользователи
        new_today_res = await session.execute(
            select(func.count(User.id)).where(
                User.source == "bot",
                User.created_at >= today_start
            )
        )
        new_today = new_today_res.scalar() or 0

        new_week_res = await session.execute(
            select(func.count(User.id)).where(
                User.source == "bot",
                User.created_at >= week_ago
            )
        )
        new_week = new_week_res.scalar() or 0

        new_month_res = await session.execute(
            select(func.count(User.id)).where(
                User.source == "bot",
                User.created_at >= month_ago
            )
        )
        new_month = new_month_res.scalar() or 0

        # Активные VPN подписки
        active_res = await session.execute(
            select(func.count(User.id)).where(
                User.vpn_subscription_end > now,
                User.source == "bot"
            )
        )
        active = active_res.scalar() or 0

        # Истекают сегодня
        expire_today_res = await session.execute(
            select(func.count(User.id)).where(
                User.vpn_subscription_end > now,
                User.vpn_subscription_end <= today_start + timedelta(days=1),
                User.source == "bot"
            )
        )
        expire_today = expire_today_res.scalar() or 0

        # Истекают в ближайшие 7 дней (включая сегодня)
        expire_7d_res = await session.execute(
            select(func.count(User.id)).where(
                User.vpn_subscription_end > now,
                User.vpn_subscription_end <= week_later,
                User.source == "bot"
            )
        )
        expire_7d = expire_7d_res.scalar() or 0

        # Истекают в ближайшие 30 дней
        expire_30d_res = await session.execute(
            select(func.count(User.id)).where(
                User.vpn_subscription_end > now,
                User.vpn_subscription_end <= month_later,
                User.source == "bot"
            )
        )
        expire_30d = expire_30d_res.scalar() or 0

        # Истекшие (окончившиеся)
        expired_res = await session.execute(
            select(func.count(User.id)).where(
                User.vpn_subscription_end <= now,
                User.vpn_subscription_end.isnot(None),
                User.source == "bot"
            )
        )
        expired = expired_res.scalar() or 0

        # Без подписки (никогда не было vpn_subscription_end)
        no_sub_res = await session.execute(
            select(func.count(User.id)).where(
                User.vpn_subscription_end.is_(None),
                User.source == "bot"
            )
        )
        no_sub = no_sub_res.scalar() or 0

        # Средний остаток дней у активных
        avg_days_res = await session.execute(
            select(func.avg(User.vpn_subscription_end - now)).where(
                User.vpn_subscription_end > now,
                User.source == "bot"
            )
        )
        avg_days = avg_days_res.scalar()
        try:
            avg_days = int(avg_days) if avg_days is not None else 0
        except (TypeError, ValueError):
            avg_days = 0

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

# ---------- Запуск ----------
async def start_polling():
    await startup()
    for attempt in range(5):
        try:
            await dp.start_polling(admin_bot)
            break
        except Exception as e:
            logger.warning(f"Admin polling attempt {attempt+1} failed: {e}")
            await asyncio.sleep(2)
    else:
        logger.error("Could not start admin polling after 5 attempts")