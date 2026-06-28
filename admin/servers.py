from datetime import datetime, timezone
import logging
from urllib.parse import urlparse
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from config import ADMIN_CHAT_ID
from db.base import AsyncSessionLocal, retry_db_operation
from db.crud_servers import add_server, get_all_servers, update_server, delete_server
from db.models import VPNServer
from handlers import get_server_pool
import admin.bot
from utils.encryption import encrypt_password

logger = logging.getLogger(__name__)
router = Router()

# ---------- FSM состояния ----------
class ServerForm(StatesGroup):
    name = State()
    base_url = State()
    inbound_id = State()
    username = State()
    password = State()
    weight = State()

def is_admin(user_id: int) -> bool:
    return str(user_id) == ADMIN_CHAT_ID

def parse_panel_url(url: str):
    parsed = urlparse(url)
    host = parsed.hostname
    port = parsed.port if parsed.port else 443
    api_path = parsed.path.rstrip('/')
    return host, port, api_path

@retry_db_operation(max_retries=3)
async def cmd_addserver(message: Message):
    """
    Добавляет новый VPN-сервер в БД.
    Формат: /addserver <name> <host> <port> <inbound_id> <username> <password> <api_path> <sub_port> [weight]
    Пример: /addserver MainServer vpn.example.com 443 1 admin pass /api 2096 10
    Все параметры обязательны, кроме weight (по умолчанию 1).
    """
    try:
        args = message.text.split()
        if len(args) < 8 or len(args) > 9:
            await message.answer(
                "❌ Неверный формат.\n"
                "Используйте: `/addserver <name> <host> <port> <inbound_id> <username> <password> <api_path> <sub_port> [weight]`\n"
                "Пример: `/addserver MainServer vpn.example.com 443 1 admin pass /api 2096 10`",
                parse_mode="Markdown"
            )
            return

        name = args[1]
        host = args[2]
        port = int(args[3])
        inbound_id = int(args[4])
        username = args[5]
        password = args[6]
        api_path = args[7]
        sub_port = int(args[8])
        weight = int(args[9]) if len(args) == 9 else 1

        # Шифруем пароль перед сохранением
        encrypted_password = encrypt_password(password)

        async with AsyncSessionLocal() as session:
            new_server = VPNServer(
                name=name,
                host=host,
                port=port,
                inbound_id=inbound_id,
                username=username,
                password=encrypted_password,
                api_path=api_path,
                sub_port=sub_port,
                is_active=True,
                weight=weight,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc)
            )
            session.add(new_server)
            await session.commit()

        await message.answer(
            f"✅ Сервер **{name}** успешно добавлен (ID: {new_server.id}).",
            parse_mode="Markdown"
        )
        logger.info(f"Admin added server {name} (ID: {new_server.id})")

    except ValueError as e:
        await message.answer(f"❌ Ошибка в аргументах: {e}")
    except IntegrityError as e:
        await message.answer("❌ Сервер с таким именем уже существует.")
    except Exception as e:
        logger.error(f"Error in cmd_addserver: {e}", exc_info=True)
        await message.answer("❌ Ошибка при добавлении сервера.")

@router.message(ServerForm.name)
async def process_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(ServerForm.base_url)
    await message.answer(
        "Введите полный URL панели 3x‑UI (например, https://185.5.75.235:42347/cNDsqfzYXWpCBcaddZ):"
    )

@router.message(ServerForm.base_url)
async def process_base_url(message: types.Message, state: FSMContext):
    raw_url = message.text.strip()
    try:
        host, port, api_path = parse_panel_url(raw_url)
    except Exception as e:
        await message.answer(f"Не удалось распознать URL: {e}\nПопробуйте ещё раз:")
        admin.bot.log_error(f"Parse URL error in addserver: {e}", notify_admin=False)  # <-- добавлен log_error
        return
    await state.update_data(base_url=raw_url, host=host, port=port, api_path=api_path)
    await state.set_state(ServerForm.inbound_id)
    await message.answer("Введите inbound_id (ID входящего подключения в 3x‑UI):")

@router.message(ServerForm.inbound_id)
async def process_inbound_id(message: types.Message, state: FSMContext):
    try:
        inbound_id = int(message.text.strip())
    except ValueError:
        await message.answer("inbound_id должен быть числом. Попробуйте ещё раз:")
        admin.bot.log_error(f"Invalid inbound_id in addserver: {message.text}", notify_admin=False)  # <-- добавлен log_error
        return
    await state.update_data(inbound_id=inbound_id)
    await state.set_state(ServerForm.username)
    await message.answer("Введите имя пользователя для доступа к 3x‑UI:")

@router.message(ServerForm.username)
async def process_username(message: types.Message, state: FSMContext):
    await state.update_data(username=message.text.strip())
    await state.set_state(ServerForm.password)
    await message.answer("Введите пароль для доступа к 3x‑UI:")

@router.message(ServerForm.password)
async def process_password(message: types.Message, state: FSMContext):
    await state.update_data(password=message.text.strip())
    await state.set_state(ServerForm.weight)
    await message.answer("Введите вес сервера (целое число, чем больше, тем чаще будет выбираться). По умолчанию 1:")

@router.message(ServerForm.weight)
async def process_weight(message: types.Message, state: FSMContext):
    weight_str = message.text.strip()
    weight = int(weight_str) if weight_str.isdigit() else 1
    data = await state.get_data()
    server = await add_server(
        name=data['name'],
        host=data['host'],
        port=data['port'],
        inbound_id=data['inbound_id'],
        username=data['username'],
        password=data['password'],
        api_path=data['api_path'],
        sub_port=2096,
        weight=weight
    )
    if server:
        pool = get_server_pool()
        await pool.refresh_servers()
        await message.answer(
            f"✅ Сервер '{data['name']}' добавлен с ID {server.id}\n"
            f"URL: {data['base_url']}\n"
            f"Вес: {weight}"
        )
    else:
        await message.answer(f"❌ Сервер с именем '{data['name']}' уже существует.")
    await state.clear()

@retry_db_operation(max_retries=3)
async def cmd_listservers(message: Message):
    """
    Выводит список всех VPN-серверов с их статусом.
    """
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(VPNServer).order_by(VPNServer.id)
            )
            servers = result.scalars().all()

            if not servers:
                await message.answer("📭 Список серверов пуст.")
                return

            text = "🖥️ **Список VPN-серверов**\n\n"
            for s in servers:
                status_emoji = "🟢" if s.is_active else "🔴"
                # Расшифровываем пароль только для отображения (если нужно)
                # Но лучше не выводить пароль в открытом виде
                text += (
                    f"{status_emoji} **ID:** {s.id}\n"
                    f"   **Название:** {s.name}\n"
                    f"   **Хост:** {s.host}:{s.port}\n"
                    f"   **Inbound ID:** {s.inbound_id}\n"
                    f"   **Вес:** {s.weight}\n"
                    f"   **Активен:** {'Да' if s.is_active else 'Нет'}\n"
                    f"   **Создан:** {s.created_at.strftime('%d.%m.%Y %H:%M')}\n"
                    f"   **Обновлён:** {s.updated_at.strftime('%d.%m.%Y %H:%M')}\n\n"
                )

            # Если слишком длинное сообщение, обрезаем или разбиваем
            if len(text) > 4000:
                # Отправляем по частям или сохраняем в файл
                await message.answer("⚠️ Список слишком большой. Отправляю файлом.")
                # Можно сохранить в txt и отправить документом
                import io
                file = io.BytesIO(text.encode('utf-8'))
                file.name = "servers.txt"
                await message.answer_document(file, caption="Список серверов")
            else:
                await message.answer(text, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Error in cmd_listservers: {e}", exc_info=True)
        await message.answer("❌ Ошибка при получении списка серверов.")

@router.message(Command("removeserver"))
async def cmd_removeserver(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа.")
        return
    args = message.text.split()
    if len(args) != 2:
        await message.answer("Используйте: /removeserver <id>")
        return
    try:
        server_id = int(args[1])
    except ValueError:
        await message.answer("ID должен быть числом.")
        admin.bot.log_error(f"Invalid server id in removeserver: {args[1]}", notify_admin=False)  # <-- добавлен log_error
        return

    from sqlalchemy import select, func
    from db.base import AsyncSessionLocal
    from db.models import BotUser

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(func.count()).select_from(BotUser).where(BotUser.server_id == server_id)
        )
        count = result.scalar() or 0
        if count > 0:
            await message.answer(
                f"❌ Невозможно удалить сервер (ID {server_id}), так как к нему привязано {count} пользователей.\n"
                "Сначала отзовите подписки у этих пользователей или переназначьте их на другой сервер."
            )
            return

    if await delete_server(server_id):
        pool = get_server_pool()
        await pool.refresh_servers()
        await message.answer(f"✅ Сервер {server_id} удалён.")
    else:
        await message.answer("❌ Сервер не найден.")

@router.message(Command("serversetactive"))
async def cmd_serversetactive(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа.")
        return
    args = message.text.split()
    if len(args) != 3:
        await message.answer("Используйте: /serversetactive <id> <0|1>")
        return
    try:
        server_id = int(args[1])
        is_active = bool(int(args[2]))
    except ValueError:
        await message.answer("ID и статус (0 или 1) должны быть числами.")
        admin.bot.log_error(f"Invalid args in serversetactive: {args[1:]}", notify_admin=False)  # <-- добавлен log_error
        return
    if await update_server(server_id, is_active=is_active):
        pool = get_server_pool()
        await pool.refresh_servers()
        await message.answer(f"✅ Статус сервера {server_id} изменён на {'активен' if is_active else 'неактивен'}.")
    else:
        await message.answer("❌ Сервер не найден.")