import asyncio
import logging
from collections import deque
from datetime import datetime, timedelta, timezone
from io import BytesIO

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import BotCommand, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from sqlalchemy import select, text, func

from config import ADMIN_BOT_TOKEN, ADMIN_CHAT_ID, TOKEN as MAIN_BOT_TOKEN
from db.base import engine, AsyncSessionLocal
from db.models import BotUser
from db.crud import (
    get_or_create_bot_user,
    set_vpn_subscription,
    get_vpn_end,
    is_vpn_active,
    set_vpn_client_id,
    get_vpn_client_id,
    add_category,
    get_all_categories,
    rename_category,
    delete_category,
    add_prompt,
    get_prompts_by_category,
    update_prompt,
    delete_prompt,
    get_prompt_by_id,
)
from services.vpn_provider import vpn_provider
from services.vpn_manager import VPNManager
from web.services.auth import PromptService

logger = logging.getLogger(__name__)

error_log = deque(maxlen=10)
admin_bot: Bot | None = None
main_bot: Bot | None = None

# ---------- Функция отправки алертов ----------
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
        BotCommand(command="health", description="Проверка состояния"),
        BotCommand(command="errors", description="Последние ошибки"),
        BotCommand(command="broadcast", description="Рассылка текста или медиа (reply на сообщение)"),
        BotCommand(command="userinfo", description="Информация о пользователе (telegram_id)"),
        BotCommand(command="grant", description="Выдать/продлить VPN-подписку (telegram_id дни)"),
        BotCommand(command="revoke", description="Отозвать VPN-подписку (telegram_id)"),
        BotCommand(command="stats", description="Статистика по подпискам"),
        BotCommand(command="addcategory", description="Добавить категорию промптов"),
        BotCommand(command="renamecategory", description="Переименовать категорию"),
        BotCommand(command="deletecategory", description="Удалить категорию"),
        BotCommand(command="addprompt", description="Добавить новый промпт (пошагово)"),
        BotCommand(command="editprompt", description="Редактировать промпт (id поле=значение)"),
        BotCommand(command="deleteprompt", description="Удалить промпт (id)"),
        BotCommand(command="listprompts", description="Показать промпты (можно с категорией)"),
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
    logger.info("Admin bot stopped")

dp = Dispatcher()

# ---------- Состояния для FSM (добавление промпта) ----------
class PromptForm(StatesGroup):
    category = State()
    title = State()
    description = State()
    content = State()
    is_free = State()

# ==================== Базовые команды ====================
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
        "/addcategory <название> – создать категорию\n"
        "/renamecategory <старое> <новое> – переименовать\n"
        "/deletecategory <название> – удалить категорию\n"
        "/addprompt – добавление промпта (пошагово)\n"
        "/editprompt <id> <поле=значение> – изменить промпт\n"
        "/deleteprompt <id> – удалить промпт\n"
        "/listprompts [категория] – список промптов\n"
    )
    await message.answer(text)

@dp.message(Command("health"))
async def cmd_health(message: types.Message):
    status = "✅ Статус:\n"
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        status += "• БД: подключена\n"
    except Exception as e:
        status += f"• БД: ошибка ({e})\n"
    try:
        if await vpn_provider.login():
            status += "• VPN-панель: авторизована\n"
        else:
            status += "• VPN-панель: не авторизована\n"
    except Exception as e:
        status += f"• VPN-панель: ошибка ({e})\n"
    await message.answer(status)

@dp.message(Command("errors"))
async def cmd_errors(message: types.Message):
    if not error_log:
        await message.answer("✅ Нет сохранённых ошибок.")
        return
    text = "📋 Последние ошибки:\n"
    for i, err in enumerate(reversed(error_log), 1):
        text += f"{i}. {err}\n"
    await message.answer(text)

# ==================== Рассылка ====================
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
            select(BotUser.telegram_id).where(BotUser.telegram_id.isnot(None))
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

# ==================== Управление пользователями ====================
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
        user = await get_or_create_bot_user(tid, session=session)
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
            f"👤 Пользователь: {user.telegram_id}\n"
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

    try:
        async with AsyncSessionLocal() as session:
            user = await get_or_create_bot_user(tid, session=session)
            has_active_key = user.vpn_client_id and user.vpn_subscription_end and user.vpn_subscription_end > datetime.utcnow()
            if has_active_key:
                await set_vpn_subscription(tid, days)
                end_date = user.vpn_subscription_end.strftime('%d.%m.%Y') if user.vpn_subscription_end else "неизвестно"
                await message.answer(f"✅ VPN-подписка для {tid} продлена на {days} дн. до {end_date}. Ключ не изменялся.")
                return

        await set_vpn_subscription(tid, days)
        manager = VPNManager()
        link = await manager.create_key(tid, days)
        await manager.close()

        async with AsyncSessionLocal() as session:
            user = await get_or_create_bot_user(tid, session=session)
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

    try:
        manager = VPNManager()
        success = await manager.revoke_key(tid)
        await manager.close()

        if success:
            async with AsyncSessionLocal() as session:
                user = await get_or_create_bot_user(tid, session=session)
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

# ==================== Статистика ====================
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
        total_res = await session.execute(select(func.count(BotUser.id)))
        total = total_res.scalar() or 0

        new_today_res = await session.execute(
            select(func.count(BotUser.id)).where(BotUser.created_at >= today_start))
        new_today = new_today_res.scalar() or 0

        new_week_res = await session.execute(
            select(func.count(BotUser.id)).where(BotUser.created_at >= week_ago))
        new_week = new_week_res.scalar() or 0

        new_month_res = await session.execute(
            select(func.count(BotUser.id)).where(BotUser.created_at >= month_ago))
        new_month = new_month_res.scalar() or 0

        active_res = await session.execute(
            select(func.count(BotUser.id)).where(BotUser.vpn_subscription_end > now))
        active = active_res.scalar() or 0

        expire_today_res = await session.execute(
            select(func.count(BotUser.id)).where(
                BotUser.vpn_subscription_end > now,
                BotUser.vpn_subscription_end <= today_start + timedelta(days=1)))
        expire_today = expire_today_res.scalar() or 0

        expire_7d_res = await session.execute(
            select(func.count(BotUser.id)).where(
                BotUser.vpn_subscription_end > now,
                BotUser.vpn_subscription_end <= week_later))
        expire_7d = expire_7d_res.scalar() or 0

        expire_30d_res = await session.execute(
            select(func.count(BotUser.id)).where(
                BotUser.vpn_subscription_end > now,
                BotUser.vpn_subscription_end <= month_later))
        expire_30d = expire_30d_res.scalar() or 0

        expired_res = await session.execute(
            select(func.count(BotUser.id)).where(
                BotUser.vpn_subscription_end <= now,
                BotUser.vpn_subscription_end.isnot(None)))
        expired = expired_res.scalar() or 0

        no_sub_res = await session.execute(
            select(func.count(BotUser.id)).where(BotUser.vpn_subscription_end.is_(None)))
        no_sub = no_sub_res.scalar() or 0

        avg_days_res = await session.execute(
            select(func.avg(BotUser.vpn_subscription_end - now)).where(
                BotUser.vpn_subscription_end > now))
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

# ==================== Управление категориями ====================
@dp.message(Command("addcategory"))
async def cmd_addcategory(message: types.Message):
    if str(message.from_user.id) != ADMIN_CHAT_ID:
        await message.answer("❌ Нет доступа.")
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Используйте: /addcategory <название>")
        return
    name = args[1].strip()
    cat = await add_category(name)
    if cat:
        PromptService.invalidate()
        await message.answer(f"✅ Категория '{name}' создана.")
    else:
        await message.answer(f"❌ Категория '{name}' уже существует.")

@dp.message(Command("renamecategory"))
async def cmd_renamecategory(message: types.Message):
    if str(message.from_user.id) != ADMIN_CHAT_ID:
        await message.answer("❌ Нет доступа.")
        return
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.answer("Используйте: /renamecategory <старое> <новое>")
        return
    old, new = args[1], args[2]
    if await rename_category(old, new):
        PromptService.invalidate()
        await message.answer(f"✅ Категория переименована в '{new}'.")
    else:
        await message.answer("❌ Категория не найдена.")

@dp.message(Command("deletecategory"))
async def cmd_deletecategory(message: types.Message):
    if str(message.from_user.id) != ADMIN_CHAT_ID:
        await message.answer("❌ Нет доступа.")
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Используйте: /deletecategory <название>")
        return
    name = args[1].strip()
    if await delete_category(name):
        PromptService.invalidate()
        await message.answer(f"✅ Категория '{name}' и все её промпты удалены.")
    else:
        await message.answer("❌ Категория не найдена.")

# ==================== Управление промптами ====================
@dp.message(Command("addprompt"))
async def cmd_addprompt(message: types.Message, state: FSMContext):
    if str(message.from_user.id) != ADMIN_CHAT_ID:
        await message.answer("❌ Нет доступа.")
        return
    await state.set_state(PromptForm.category)
    await message.answer("Введите название категории:")

@dp.message(PromptForm.category)
async def process_category(message: types.Message, state: FSMContext):
    cat_name = message.text.strip()
    cats = await get_all_categories()
    if cat_name not in cats:
        await message.answer("Такой категории нет. Сначала создайте её через /addcategory.")
        await state.clear()
        return
    await state.update_data(category=cat_name)
    await state.set_state(PromptForm.title)
    await message.answer("Введите название промпта:")

@dp.message(PromptForm.title)
async def process_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await state.set_state(PromptForm.description)
    await message.answer("Введите краткое описание:")

@dp.message(PromptForm.description)
async def process_description(message: types.Message, state: FSMContext):
    await state.update_data(description=message.text.strip())
    await state.set_state(PromptForm.content)
    await message.answer("Введите полный текст промпта:")

@dp.message(PromptForm.content)
async def process_content(message: types.Message, state: FSMContext):
    await state.update_data(content=message.text.strip())
    await state.set_state(PromptForm.is_free)
    await message.answer("Промпт бесплатный? (да/нет)")

@dp.message(PromptForm.is_free)
async def process_is_free(message: types.Message, state: FSMContext):
    answer = message.text.lower().strip()
    is_free = answer in ("да", "yes", "1", "true")
    data = await state.get_data()
    prompt = await add_prompt(
        title=data["title"],
        description=data["description"],
        content=data["content"],
        category_name=data["category"],
        is_free=is_free
    )
    if prompt:
        PromptService.invalidate()
        await message.answer(f"✅ Промпт '{prompt.title}' (ID {prompt.id}) добавлен!")
    else:
        await message.answer("❌ Ошибка при добавлении. Проверьте категорию.")
    await state.clear()

@dp.message(Command("editprompt"))
async def cmd_editprompt(message: types.Message):
    if str(message.from_user.id) != ADMIN_CHAT_ID:
        await message.answer("❌ Нет доступа.")
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Используйте: /editprompt <id> <поле=значение> ...")
        return
    try:
        prompt_id = int(args[1])
    except ValueError:
        await message.answer("ID должен быть числом.")
        return
    updates = {}
    for arg in args[2:]:
        if "=" in arg:
            key, val = arg.split("=", 1)
            updates[key] = val
    if not updates:
        await message.answer("Укажите поля для обновления, например: /editprompt 5 title=Новый заголовок is_free=true")
        return
    if await update_prompt(prompt_id, **updates):
        PromptService.invalidate()
        await message.answer("✅ Промпт обновлён.")
    else:
        await message.answer("❌ Промпт не найден или ошибка.")

@dp.message(Command("deleteprompt"))
async def cmd_deleteprompt(message: types.Message):
    if str(message.from_user.id) != ADMIN_CHAT_ID:
        await message.answer("❌ Нет доступа.")
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Используйте: /deleteprompt <id>")
        return
    try:
        prompt_id = int(args[1])
    except ValueError:
        await message.answer("ID должен быть числом.")
        return
    if await delete_prompt(prompt_id):
        PromptService.invalidate()
        await message.answer("✅ Промпт удалён.")
    else:
        await message.answer("❌ Промпт не найден.")

@dp.message(Command("listprompts"))
async def cmd_listprompts(message: types.Message):
    if str(message.from_user.id) != ADMIN_CHAT_ID:
        await message.answer("❌ Нет доступа.")
        return
    args = message.text.split(maxsplit=1)
    category = args[1] if len(args) > 1 else None
    prompts = await get_prompts_by_category(category)
    if not prompts:
        await message.answer("Промптов не найдено.")
        return
    lines = []
    for p in prompts[:20]:
        lines.append(f"{p['id']}: {p['title']} [{p['category']}] {'(бесплатный)' if p['is_free'] else ''}")
    await message.answer("📋 Промпты:\n" + "\n".join(lines))
    if len(prompts) > 20:
        await message.answer("Показаны первые 20. Уточните категорию.")

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